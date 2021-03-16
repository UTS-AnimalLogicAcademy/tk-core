# Copyright (c) 2016 Shotgun Software Inc.
#
# CONFIDENTIAL AND PROPRIETARY
#
# This work is provided "AS IS" and subject to the Shotgun Pipeline Toolkit
# Source Code License included in this distribution package. See LICENSE.
# By accessing, using, copying or modifying this work you indicate your
# agreement to the Shotgun Pipeline Toolkit Source Code License. All rights
# not expressly granted therein are reserved by Shotgun Software Inc.

try:
    from importlib import reload # python3
except:
    pass

import os
import sys
import copy

try:
    from StringIO import StringIO ## for Python 2
except ImportError:
    from io import StringIO ## for Python 3

from .base import IODescriptorBase
from ..errors import TankDescriptorError
from ...util import ShotgunPath
from ... import LogManager

log = LogManager.get_logger(__name__)

# put this in a config!!!
# TBR DGH270217 These are hardcoded environment variables. I believe there
# is not an easy way out of this as we need to get access to REZ
# to be able to get an environment to resolve. Chicken/egg situation.

os.environ["REZ_CONFIG_FILE"]="/mnt/ala/software/pipeline/config/rezconfig.py"
os.environ["REZ_PATH"] = "/mnt/ala/software/ext_packages/rez/2.2.0/platform-linux/arch-x86_64/os-RedHatEnterpriseServer-6.8/rez"

def toStrDict(dictobj):
    return dict([(str(k), str(v)) for k, v in dictobj.items()])

cached_rez_contexts = {}

class IODescriptorRez(IODescriptorBase):
    """
    Represents a local item on disk resolved by rez. 
    This item is never downloaded into the local storage,
    you interact with it directly::

        {"type": "rez", "package": "package01 package02", "path": "bundle"}

    Optional parameters are possible::

        {"type": "rez", "package": "package01 package02", "name": "my-app",  "path": "bundle"}

        {"type": "rez",
         "path": "bundle",
         "linux_package": "package01 package02",
         "windows_package": "package01 package02",
         "mac_package": "package01 package02" }

    Name is optional and if not specified will be determined based on folder path.
    If name is not specified and path is /tmp/foo/bar, the name will set to 'bar'
    """

    def __init__(self, descriptor_dict, sg_connection, bundle_type):
        """
        Constructor

        :param descriptor_dict: descriptor dictionary describing the bundle
        :return: Descriptor instance
        """

        super(IODescriptorRez, self).__init__(descriptor_dict, sg_connection, bundle_type)

        self._mod_rez = None
        self._mod_resolved_context = None
        self._mod_package_repository_manager = None

        self._descriptor_dict = descriptor_dict
        self._validate_descriptor(
            descriptor_dict,
            required=["type", "path"],
            optional=["name", "package", "linux_package", "mac_package", "windows_package"]
        )

        # platform specific location support
        platform_key = IODescriptorRez.get_rez_storage_key()
        self._package_path = descriptor_dict["path"]

        if "package" in descriptor_dict:
            # first look for 'path' key
            self._packages = descriptor_dict["package"]
            # self._path = descriptor_dict["path"]
            self._multi_os_descriptor = False
        elif platform_key in descriptor_dict:
            # if not defined, look for os specific key
            self._packages = descriptor_dict[platform_key]
            # self._path = descriptor_dict[platform_key]
            self._multi_os_descriptor = True
        else:
            raise TankDescriptorError(
                "Invalid descriptor! Could not find a package list or a %s entry in the "
                "descriptor dict %s." % (platform_key, descriptor_dict)
            )


        self._resolved_packages = []
        # resolved the packages environment
        context = self.resolve_context([self._packages])

        if context:
            # context_info = StringIO.StringIO()
            context_info = StringIO()
            context.print_info(buf=context_info)
            log.debug(context_info.getvalue())
            context_info.close()

            self._resolved_context = context
            self._path = self.resolve_path(context)

        # lastly, resolve environment variables and ~
        self._path = os.path.expandvars(self._path)
        self._path = os.path.expanduser(self._path)

        # and normalize:
        self._path = os.path.normpath(self._path)

        # # if there is a version defined in the descriptor dict
        # # (this is handy when doing framework development, but totally
        # #  non-required for finding the code)
        # self._version = descriptor_dict.get("version") or "Undefined"

        self._sg_connection = sg_connection
        self._bundle_type = bundle_type
        self._name = descriptor_dict.get("name")
        self._version = descriptor_dict.get("version")
        self._label = descriptor_dict.get("label")

        # if there is a name defined in the descriptor dict then lets use
        # this, otherwise we'll fall back to the folder name:
        self._name = descriptor_dict.get("name")
        if not self._name:
            # fall back to the folder name
            bn = os.path.basename(self._path)
            self._name, _ = os.path.splitext(bn)


    REZ_PACKAGE_FIELDS = ["windows_package", "linux_package", "mac_package"]

    def resolve_path(self, context):
        for resolved_package in context.resolved_packages:
            if resolved_package.name == self._packages:
                path = os.path.join(resolved_package.root, self._package_path)
        return path

    def resolve_context(self, packages):
        # print("== Resolving with REZ")

        if "USE_REZ_CACHE" not in os.environ:
            # print("= NOT USING REZ CACHE")
            if not os.environ.get('REZ_PATH'):
                raise TankDescriptorError("Could not find REZ_PATH in the envioronment!")

            # add rez python to the path, so we can resolve the environment
            rez_path = os.environ['REZ_PATH']+'/..'
            if (rez_path not in sys.path):
                sys.path.insert(0, rez_path)
                log.debug("Adding rez path: " + rez_path)
            
            # ----------------------------------------------------------------------
            # HACK ON
            # ----------------------------------------------------------------------
            # DGH140817 . For some reason (to be checked more in depth later)
            # rez under shotgun context does not realize of new packages
            # at least in local! This solves the problem in a VERY rudimentary way
            import rez
            reload(rez)

            import rez.package_repository
            reload(rez.package_repository)

            import rez.packages_
            reload(rez.packages_)

            import rez.vendor.memcache
            reload(rez.vendor.memcache)
            # ----------------------------------------------------------------------
            # HACK OFF
            # ----------------------------------------------------------------------

            import rez.resolved_context
            reload(rez.resolved_context)

            # resolved the packages environment
            context = None
            try:
                context = rez.resolved_context.ResolvedContext(packages)
            except Exception as e:
                log.error(e)
                pass

            return context
        else:
            # print("= USING REZ CACHE")
            if not os.environ.get('REZ_PATH'):
                raise TankDescriptorError("Could not find REZ_PATH in the envioronment!")

            # add rez python to the path, so we can resolve the environment
            rez_path = os.environ['REZ_PATH']+'/..'
            if (rez_path not in sys.path):
                sys.path.insert(0, rez_path)
                log.debug("Adding rez path: " + rez_path)
            
            # ----------------------------------------------------------------------
            # HACK ON
            # ----------------------------------------------------------------------
            # DGH140817 . For some reason (to be checked more in depth later)
            # rez under shotgun context does not realize of new packages
            # at least in local! This solves the problem in a VERY rudimentary way
            if self._mod_rez is None:
                import rez
                reload(rez)
                self._mod_rez = rez

            if self._mod_resolved_context is None:
                import rez.resolved_context
                reload(rez.resolved_context)
                self._mod_resolved_context = rez.resolved_context

            if self._mod_package_repository_manager is None:
                from rez.packages_ import package_repository_manager
                self._mod_package_repository_manager = package_repository_manager

            # reset the caching if this has been specified externally
            if 'SG_CACHE_DYNAMIC_DESCRIPTORS_RESET' in os.environ:
                log.debug("[ REZ Descriptor ] Clearing REZ package caches")
                # reload modules
                import rez
                reload(rez)

                import rez.resolved_context
                reload(rez.resolved_context)

                self._mod_rez = rez            
                self._mod_resolved_context = rez.resolved_context
                self._mod_package_repository_manager.clear_caches()

                # clear flag for resetting the cache
                global cached_rez_contexts
                cached_rez_contexts = {}
                if 'SG_CACHE_DYNAMIC_DESCRIPTORS_RESET' in os.environ:
                    del os.environ['SG_CACHE_DYNAMIC_DESCRIPTORS_RESET']


            # by default cache rez envs
            packages_id = " ".join(packages)
            
            if (packages_id in cached_rez_contexts):
                log.debug("[ REZ Descriptor ] Retrieving the cached context for packages: %s" % packages)
                context = cached_rez_contexts[packages_id]
            else:
                self._mod_package_repository_manager.clear_caches()
                # resolved the packages environment
                context = None
                try:
                    context = self._mod_resolved_context.ResolvedContext(packages)
                    log.debug("[ REZ Descriptor ] Storing the cached context for packages: %s" % packages)
                    cached_rez_contexts[packages_id] = context
                except Exception as e:
                    log.error(e)
                    pass

            return context

    @staticmethod
    def get_rez_storage_key(platform=sys.platform):
        """
        Given a ``sys.platform`` constant, resolve a Shotgun storage key

        Shotgun local storages handle operating systems using
        the three keys 'windows_path, 'mac_path' and 'linux_path',
        also defined as ``IODescriptorRez.REZ_PACKAGE_FIELDS``

        This method resolves the right key given a std. python
        sys.platform::


            >>> p.get_rez_storage_key('win32')
            'windows_package'

            # if running on a mac
            >>> p.get_rez_storage_key()
            'mac_package'

        :param platform: sys.platform style string, e.g 'linux2',
                         'win32' or 'darwin'.
        :returns: rez storage path as string.
        """
        if platform == "win32":
            return "windows_package"
        elif platform == "darwin":
            return "mac_package"
        elif platform.startswith("linux"):
            return "linux_package"
        else:
            raise ValueError(
                "Cannot resolve rez storage - unsupported "
                "os platform '%s'" % platform
            )

    def get_resolved_packages(self):
        return self._resolved_context.resolved_packages

    def __eq__(self, other):
        # By default, we can assume equality if the packages resolved
        # are the same ones
        if isinstance(other, self.__class__):
            return self.get_resolved_packages() == other.get_resolved_packages()
        else:
            return False

    def _get_bundle_cache_path(self, bundle_cache_root):
        """
        Given a cache root, compute a cache path suitable
        for this descriptor, using the 0.18+ path format.

        :param bundle_cache_root: Bundle cache root path
        :return: Path to bundle cache location
        """
        return self._path

    def _get_cache_paths(self):
        """
        Get a list of resolved paths, starting with the primary and
        continuing with alternative locations where it may reside.

        Note: This method only computes paths and does not perform any I/O ops.

        :return: List of path strings
        """
        
        return [self._path]

    def get_system_name(self):
        """
        Returns a short name, suitable for use in configuration files
        and for folders on disk, e.g. 'tk-maya'
        """
        return self._name

    def get_version(self):
        """
        Returns the version number string for this item
        """
        # version number does not make sense for this type of item
        # so a fixed string is returned
        return self._version

    def exists_local(self):
        context = self.resolve_context([self._packages])
        if context:
            path = self.resolve_path(context)
            return os.path.exists(path)
        return False

    def download_local(self):
        """
        Retrieves this version to local repo
        """
        # ensure that this exists on disk
        if not self.exists_local():
            raise TankDescriptorError("%s does not point at a valid bundle on disk!" % self)

    def is_immutable(self):
        """
        Returns true if this items content never changes
        """
        return False

    def get_latest_version(self, constraint_pattern=None):
        """
        Returns a descriptor object that represents the latest version.

        :param constraint_pattern: If this is specified, the query will be constrained
               by the given pattern. Version patterns are on the following forms:

                - v0.1.2, v0.12.3.2, v0.1.3beta - a specific version
                - v0.12.x - get the highest v0.12 version
                - v1.x.x - get the highest v1 version

        :returns: IODescriptorRez object
        """
#        log.info("get_latest_version", str_rep)
        log.info("get_latest_version")
        return IODescriptorRez(self._descriptor_dict, self._sg_connection, self._bundle_type)

    def get_latest_cached_version(self, constraint_pattern=None):
        """
        Returns a descriptor object that represents the latest version
        that is locally available in the bundle cache search path.

        :param constraint_pattern: If this is specified, the query will be constrained
               by the given pattern. Version patterns are on the following forms:

                - v0.1.2, v0.12.3.2, v0.1.3beta - a specific version
                - v0.12.x - get the highest v0.12 version
                - v1.x.x - get the highest v1 version

        :returns: instance deriving from IODescriptorBase or None if not found
        """
        # we are always the latest version
        # also assume that the payload always exists on disk.
        log.info("get_latest_cached_version", self)
        return IODescriptorRez(self._descriptor_dict, self._sg_connection, self._bundle_type)
        
        #return self

    def clone_cache(self, cache_root):
        """
        The descriptor system maintains an internal cache where it downloads
        the payload that is associated with the descriptor. Toolkit supports
        complex cache setups, where you can specify a series of path where toolkit
        should go and look for cached items.

        This is an advanced method that helps in cases where a user wishes to
        administer such a setup, allowing a cached payload to be copied from
        its current location into a new cache structure.

        If the descriptor's payload doesn't exist on disk, it will be downloaded.

        :param cache_root: Root point of the cache location to copy to.
        """
        # no payload is cached at all, so nothing to do
        log.debug("Clone cache for %r: Not copying anything for this descriptor type")

    def has_remote_access(self):
        """
        Probes if the current descriptor is able to handle
        remote requests. If this method returns, true, operations
        such as :meth:`download_local` and :meth:`get_latest_version`
        can be expected to succeed.

        :return: True if a remote is accessible, false if not.
        """
        # the remote is the same as the cache for path descriptors
        return True

    def can_resolve_environment(self):
        return True

    def resolve_environment(self, env):
        updated_env = copy.copy(env)
        if self._resolved_context:
            context_env = self._resolved_context.get_environ()
            updated_env.update(context_env)
        return updated_env
