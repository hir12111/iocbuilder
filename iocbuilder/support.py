'''A miscellaneous collection of fairly generic utilities.'''
import fnmatch
import itertools
import os
import os.path
import re
import subprocess
import sys
import types

from importlib import import_module


__all__ = ['Singleton', 'AutoRegisterClass', 'SameDirFile', 'quote_c_string']


# This helper routine is used by __init__.py to selectively export only those
# names announced for export by each sub-module.  Each sub-module passed is
# imported, and each name listed in its __all__ list is added to the given
# global context, and returned.
def ExportModules(globals, *modulenames):
    names = []
    for modulename in modulenames:
        module = import_module(f"iocbuilder.{modulename}")
        if hasattr(module, '__all__'):
            for name in module.__all__:
                globals[name] = getattr(module, name)
            names.extend(module.__all__)
    return names


# This automatically exports all sub-modules.
def ExportAllModules(globals):
    allfiles = [filename[:-3]
        for moduledir in globals['__path__']
        for filename in fnmatch.filter(os.listdir(moduledir), '*.py')
        if filename != '__init__.py']
    return ExportModules(globals, *allfiles)


# Creates a fully qualified module from thin air and adds it to the module
# table.
def CreateModule(module_name):
    module = types.ModuleType(module_name)
    sys.modules[module_name] = module
    return module


## Returns a full filename of a file with the given filename in the same
# directory as first_file.  Designed to be called as
#     path = SameDirFile(__file__, filename)
# to return a path to a file in the same directory as the calling module.
def SameDirFile(first_file, *filename):
    return os.path.join(os.path.dirname(first_file), *filename)


# Returns the first n elements from iter as an iterator.
def take(iter, n):
    for i in range(n):
        yield next(iter)


# This support routine chops the given list into segments no longer than size.
def choplist(list, size):
    return [list[i:i+size] for i in range(0, len(list), size)]


# Returns a sequence of letters.
def countChars(start='A', stop='Z'):
    return iter(map(chr, list(range(ord(start), ord(stop) + 1))))


# Converts a string into a form suitable for interpretation by the IOC shell
# -- actually, all we do is ensure that dangerous characters are quoted
# appropriately and enclose the whole thing in quotes.
def quote_c_string(s):

    def replace(match):
        # Replaces dodgy characters with safe replacements
        start, end = match.span()
        ch = s[start:end]
        try:
            table = {
                '\\': r'\\',    '"': r'\"',
                '\t': r'\t',    '\n': r'\n',    '\r': r'\r' }
            return table[ch]
        except KeyError:
            return r'\%03o' % ord(ch)

    return '"%s"' % unsafe_chars.sub(replace, str(s))


## An ordered dictionary, similar to that provided by Python 3, but not quite
# as complete.
class OrderedDict(dict):
    def __init__(self):
        self._keys = []
        dict.__init__(self)

    def __setitem__(self, key, value):
        if key not in self:
            self._keys.append(key)
        dict.__setitem__(self, key, value)

    def __delitem__(self, key):
        dict.__delitem__(self, key)
        self._keys.remove(key)

    def __iter__(self):
        return iter(self._keys)

    def items(self):
        return [(k, self[k]) for k in self._keys]
    def keys(self):
        return self._keys
    def values(self):
        return [self[k] for k in self._keys]
    def pop(self, key):
        if key in self._keys:
            self._keys.remove(key)
        return dict.pop(self, key)

    def setdefault(self, key, value):
        if key in self:
            return self[key]
        else:
            self[key] = value
            return value


# The SingletonMeta class is a type class for building singletons: it
# simply converts all of the methods of the class into class bound
# methods.  This means that all the data for classes generated by this
# type is stored in the class, and no instances are created.
class SingletonMeta(type):
    def __new__(cls, name, bases, dict):
        for n, v in list(dict.items()):
            if isinstance(v, types.FunctionType):
                dict[n] = classmethod(v)
        singleton = type.__new__(cls, name, bases, dict)
        singleton.__init__()
        return singleton


# The Singleton class has *no* instances: instead, all of its members are
# automatically converted into class methods, and attempts to create instances
# simply return the original class.  This behaviour is pretty transparent.
#
# The role of this Singleton class is a little unclear.  It can readily be
# argued that a Singleton class is functionally identical to a module.  Very
# true, but there are differences in syntax and perhaps in organisation.
class Singleton(object, metaclass=SingletonMeta):

    # The __init__ method of a singleton class is called as the class is being
    # declared.
    def __init__(self):
        pass

    # The default call method emulates dummy instance creation, ie just return
    # the class itself.
    def __call__(self):
        return self

    def __new__(self, cls, *argv, **argk):
        # Simply delegate __new__ to the __call__ method: this produces the
        # right behaviour, either the subclass is called or our dummy instance
        # is returned.
        #     Note that self is passed twice, because __new__ becomes
        # transformed from a static method into a class method.
        return cls.__call__(*argv, **argk)


# Meta-class to implement __super attribute in all subclasses.  To use this
# define the metaclass of the appropriate base class to be autosuper thus:
#
#     class A:
#         __metaclass__ = _autosuper_meta
#
# Then in any sub-class of A the __super attribute can be used instead of
# writing super(cls, name) thus:
#
#     class B(A):
#         def __init__(self):
#             self.__super.__init__()
#             # instead of
#             # super(B, self).__init__()
#
# The point being, of course, that simply writing
#             A.__init__(self)
# will not properly interact with calling order in the presence of multiple
# inheritance: it may be necessary to call a sibling of B instead of A at
# this point!
#
# Note that this trick does not work properly if a) the same class name
# appears more than once in the class hierarchy, and b) if the class name is
# changed after it has been constructed.  The class can be renamed during
# construction by setting the TrueName attribute.
#
#
# This meta class also supports the __init_meta__ method: if this method is
# present in the dictionary of the class it will be called after completing
# initialisation of the class.
#
# For any class with _autosuper_meta as metaclass if a method
#     __init_meta__(cls, subclass)
# is defined then it will be called when the class is declared (with subclass
# set to False) and will be called every time the class is subclassed with
# subclass set to True.
#
# This class definition is taken from
#   http://www.python.org/2.2.3/descrintro.html#metaclass_examples
class _autosuper_meta(type):

    __super = property(lambda subcls: super(_autosuper_meta, subcls))

    def __init__(cls, name, bases, dict):
        # Support renaming.
        if 'TrueName' in dict:
            name = dict['TrueName']
            cls.__name__ = name

        cls.__super.__init__(name, bases, dict)

        super_name = '_%s__super' % name.lstrip('_')
        assert not hasattr(cls, super_name), \
            'Can\'t set super_name on class %s, name conflict' % name
        setattr(cls, super_name, super(cls))

        # Support __init_meta__
        cls.__call_init_meta(set([object]), cls, False)

    def __call_init_meta(cls, visited, base, subclass):
        # This is rather painful.  Ideally each __init_meta__ call would
        # invoke the appropriate superclass ... unfortunately it can't call
        # super() because the class name isn't available yet!
        #    So instead we walk the entire class tree, calling __init_meta__
        # on all base classes ourself.
        for b in base.__bases__:
            if b not in visited:
                visited.add(b)
                cls.__call_init_meta(visited, b, True)
        if '__init_meta__' in base.__dict__:
            base.__dict__['__init_meta__'](cls, subclass)


## Class that can be subclassed to inherit autosuper behaviour.
#
# All subclasses of this class share an attribute \c __super which allows
# self.__super to be used rather than super(Class, self).
class autosuper(object, metaclass=_autosuper_meta):
    if sys.version_info.major > 2 or sys.version_info.minor >= 6:
        def __new__(cls, *args, **kargs):
            assert super(autosuper, cls).__init__ == object.__init__, \
                'Broken inheritance hierarchy?'
            return object.__new__(cls)


# This returns a meta-class which will call the given register function each
# time a sub-class instance is created.  If ignoreParent is True then the
# first class registered will be ignored.
def AutoRegisterClass(register, ignoreParent=True, superclass=type):
    firstRegister = [ignoreParent]
    class DoRegister(superclass):
        def __init__(cls, name, bases, dict):
            super(DoRegister, cls).__init__(name, bases, dict)
            if firstRegister[0]:
                firstRegister[0] = False
            else:
                register(cls, name)

    return DoRegister

# Call msi on a piece of text with a dictionary of macros, expensive but needed
# because of the stupidly complex syntax...
def msi_replace_macros(d, text):
    if '$(' in text:
        args = ['msi'] + ['-M%s=%s' % (k, str(v).replace(",undefined)", ")"))
            for k, v in list(d.items())]
        p = subprocess.Popen(args, stdout = subprocess.PIPE,
            stdin = subprocess.PIPE)
        return p.communicate(text)[0]
    else:
        return text

# Return the element child nodes of an element
def elements(node):
    return [n for n in node.childNodes if n.nodeType == n.ELEMENT_NODE]

# At end for doxygen!
unsafe_chars = re.compile(r'[\\"\1-\37]')
