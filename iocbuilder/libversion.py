#   Generic hardware module support

import sys
import os
import string
from types import ModuleType

from support import autosuper, SameDirFile, CreateModule
from configure import Configure

import hardware


__all__ = ['ModuleVersion', 'ModuleBase', 'SetModulePath', 'modules']




def SetModulePath(prod):
    '''Define the directory path for locating modules.  This works with the
    Diamond directory conventions.'''
    global prodSupport
    prodSupport = prod


def _CheckPythonModule(path, module):
    # Checks for a Python module or package at path/module, returns the path
    # to the python path to execute and a flag indicating whether the file is
    # a package.
    Places = [
        # Follow Python by first trying for a package before a plain module.
        (os.path.join(path, module, '__init__.py'), True),
        (os.path.join(path, '%s.py' % module),      False)]
    for ModuleFile, IsPackage in Places:
        if os.access(ModuleFile, os.R_OK):
            return (ModuleFile, IsPackage)
    else:
        return (None, False)



# Module version information specifying:
#   name     Directory name of module
#   version  Version of module
#   home     Home directory to locate module
class ModuleVersion:
    '''Create instances of this class to declare the version of each module
    to be used.'''

    # Restrict module names to names which can be used as identifiers.  This
    # helps a lot when generating EPICS14 IOCs.
    __ValidNameChars = set(
        string.ascii_uppercase + string.ascii_lowercase +
        string.digits + '_')

    # Set of module macro names already allocated, used to ensure no clashes.
    __MacroNames = set()

    # This is set while the module is being loaded so that we can detect
    # nested loads (really bad idea) and can treat the module name specially
    # in ModuleBase.
    _LoadingModule = None
    
    def __init__(self, libname,
            version=None, home=None, override=False, use_name=True,
            suppress_import=False, load_path=None):
        # By default pick up each module from the prod support directory.  It
        # might be quite nice to extend this with a path search.
        if home is None:
            home = prodSupport

        assert set(libname) <= set(self.__ValidNameChars), \
            'Module name %s must be a valid identifier' % libname
        self.__name = libname
        self.version = version
        self.home = home
        self.use_name = use_name

        self.__macroname = libname.upper()
        assert self.__macroname not in self.__MacroNames, \
            'Module with macro name %s already defined' % self.__macroname
        self.__MacroNames.add(self.__macroname)

        # A couple of sanity checks: libname must not be already defined iff
        # version override has not been requested.
        libDefined = libname in _ModuleVersionTable
        assert (not override) <= (not libDefined), \
               'Module %s multiply defined' % libname
        assert override <= libDefined, 'Module %s not defined' % libname
        
        # Add this to the list of module versions, create the associated
        # module and finally attempt to load any definitions associated with
        # this module.
        _ModuleVersionTable[libname] = self
        self.__CreateVersionModule()
        if suppress_import:
            print 'Import of %s skipped' % self.__name
        else:
            self.__LoadModuleDefinitions(load_path)
        

    def LibPath(self, macro_name=False):
        '''Returns the path to the module directory defined by this entry.
        If macro_name is set then a form suitable for macro expansion is
        returned.'''
        if macro_name:
            return '$(%s)' % self.__macroname
        
        path = self.home
        if self.use_name:
            path = os.path.join(path, self.__name)
        if self.version:
            path = os.path.join(path, self.version)
        return path

    def ModuleFile(self, filename):
        '''Returns an absolute path to a file within this module.'''
        filename = os.path.join(self.LibPath(), filename)
        assert os.access(filename, os.R_OK), 'File "%s" not found' % filename
        return filename

    def Name(self, macro_name = False):
        '''Returns the module name.'''
        return self.__name

    def MacroName(self):
        return self.__macroname

    # The following definitions ensure that when hashed and when compared
    # this class behaves exactly like its name: this ensures that sets and
    # sorted lists of modules behave predicably.
    def __hash__(self):         return hash(self.__name)
    def __cmp__(self, other):   return cmp(self.__name, other.__name)


    def __CreateVersionModule(self):
        # Create the associated module and record it in our list of loaded
        # modules.  If we can find any module definitions then they will be
        # loaded into this module.
        ModuleName = 'iocbuilder.modules.%s' % self.__name
        self.module = CreateModule(ModuleName)
        setattr(modules, self.__name, self.module)

        # Create some useful module properties.
        self.module.ModuleVersion = self
        self.module.LibPath = self.LibPath
        self.module.ModuleFile = self.ModuleFile


    def __LoadModuleDefinitions(self, load_path):
        if load_path:
            ModuleFile, IsPackage = _CheckPythonModule(
                load_path, self.__name)
        else:
            Places = [
                # First look for a builder package in the loaded EPICS module
                (self.LibPath(), 'builder'),
                # Failing that, try for a defaults entry.
                (SameDirFile(__file__, 'defaults'), self.__name)]
            for path, module in Places:
                ModuleFile, IsPackage = _CheckPythonModule(path, module)
                if ModuleFile:
                    break

        if ModuleFile:
            ModuleFile = os.path.abspath(ModuleFile)
            self.module.__file__ = ModuleFile
            if IsPackage:
                # Convert the module into a package by setting up the file
                # name and path so that it looks like a convincing Python
                # package.  Now executing execfile has the desired effect of
                # ensuring that all imports with ModuleFile are treated as
                # local to ModuleFile.
                self.module.__path__ = [os.path.dirname(ModuleFile)]
            
            assert self._LoadingModule is None, \
                'Calling ModuleVersion inside an EPICS module is a BAD idea!'
            ModuleVersion._LoadingModule = self
            execfile(ModuleFile, self.module.__dict__)
            ModuleVersion._LoadingModule = None
            
            if hasattr(self.module, '__all__'):
                for name in self.module.__all__:
                    assert not hasattr(hardware, name), \
                        'Value %s.%s already in hardware module' % (
                            self.__name, name)
                    setattr(hardware, name, getattr(self.module, name))
        else:
            print 'Module definitions for', self.__name, 'not found'

    

class ModuleBase(object):
    '''All entities which need to depend on module versions should subclass
    this class to obtain access to their configuration information.

    By default the name of the class will be used both as an index into the
    ModuleVersion entry and as the subdirectory name in the support directory.
    When the external name of the module doesn't match the class name then
    the symbol ModuleName should be set equal to the external module name
    thus:
        ModuleName = 'true-module-name'

    This class will always define a ModuleName symbol.  If the same module
    is to be used by all subclasses then this can be enabled by defining the
    symbol
        InheritModuleName = True
    '''

    # Meta class used for module instances: ensures that the ModuleName
    # symbol exists, defaulting to the class name.
    # 
    # Optionally the ModuleName can be inherited from the base class if the
    # symbol InheritModuleName is set to True.
    class __ModuleBaseMeta(autosuper):
        def __init__(cls, name, bases, dict):
            # This could more simply be written as autosuper.__..., but then
            # subclassing might go astray.  Module instances are already
            # broadly subclassed, so we ought to play by the rules.
            super(cls._ModuleBase__ModuleBaseMeta, cls).__init__(
                name, bases, dict)

            if hasattr(cls, 'BaseClass'):
                # This is a base class, not designed for export from a module.
                # We suppress the class attribute so that subclasses don't
                # need special treatment.  In this case no module name should
                # be specified.
                assert not hasattr(cls, 'ModuleName'), \
                    'Base classes cannot be tied to modules'
                del cls.BaseClass
            else:
                cls.ModuleSubClasses.append(cls)
                # A normal implementation class.  This needs to be tied to a
                # particular module.
                if ModuleVersion._LoadingModule is None:
                    # Module is being defined as part of the build script, not
                    # in the module.  In this case if the class doesn't
                    # already have a module name specified we'll automatically
                    # name it after itself.
                    if not hasattr(cls, 'ModuleName'):
                        cls.ModuleName = name
                else:
                    # If we're called while loading a module then force the
                    # module name to agree with the loading module: in other
                    # words, an EPICS module isn't allowed to create classes
                    # which belong to other modules.
                    name = ModuleVersion._LoadingModule.Name()
                    if 'ModuleName' in cls.__dict__:
                        assert cls.ModuleName == name, \
                            'ModuleName must be %s' % name
                        print 'Redundant ModuleName for', cls.__name__
                    cls.ModuleName = name
                cls.ModuleVersion = _ModuleVersionTable[cls.ModuleName]


    __metaclass__ = __ModuleBaseMeta

    # Setting this attribute suppresses ModuleName and ModuleVersion
    # assignment.
    BaseClass = True

    ModuleSubClasses = []

    # Set of instantiated modules as ModuleVersion instances
    _ReferencedModules = set()

    @classmethod
    def LibPath(cls, macro_name=False):
        '''Returns the path to the module.  If macro_name is set then a macro
        for the path is returned, otherwise the true path is returned.'''
        return cls.ModuleVersion.LibPath(macro_name = macro_name)

    @classmethod
    def ModuleFile(cls, filename):
        '''Returns an absolute path to a file within this module.'''
        return cls.ModuleVersion.ModuleFile(filename)

    @classmethod
    def UseModule(cls):
        cls._ReferencedModules.add(cls.ModuleVersion)

    @classmethod
    def ListModules(cls):
        '''Returns the set of all modules that have been instantiated.  The
        objects returned are ModuleVersion instances.'''
        return cls._ReferencedModules

    __call_init_once = True
    @classmethod
    def __new__(cls, *args, **kargs):
        if cls.__call_init_once:
            cls.__call_init_once = False
            cls.__init_once__()
        
        return super(ModuleBase, cls).__new__(cls, *args, **kargs)

    @classmethod
    def __init_once__(cls):
        cls.UseModule()


# Dictionary of all modules with announced versions.  This will be
# interrogated when modules are initialised.
_ModuleVersionTable = {}

# We maintain all loaded modules in a synthetic module.
modules = CreateModule('iocbuilder.modules')