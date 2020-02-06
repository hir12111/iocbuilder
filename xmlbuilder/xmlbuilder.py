#!/bin/env dls-python
from xmlstore import Store
import sys, os, shutil
from subprocess import *
from optparse import OptionParser
import xml.dom.minidom


# hacky hacky change linux-x86 to linux-x86_64 in RHEL6
def patch_arch(arch):
    lsb_release = Popen(["lsb_release", "-sr"], stdout=PIPE).communicate()[0][0]
    if lsb_release == "6" and arch == "linux-x86":
        arch = "linux-x86_64"
    return arch
    

def main():
    parser = OptionParser('usage: %prog [options] <xml-file>')
    parser.add_option(
        '-d', action='store_true', dest='debug',
        help='Print lots of debug information')
    parser.add_option(
        '-D', action='store_true', dest='DbOnly',
        help='Only output files destined for the Db dir')
    parser.add_option('-o', dest='out',
        default = os.path.join('..', '..', 'iocs'),
        help='Output directory for ioc')
    parser.add_option(
        '--doc', dest='doc',
        help='Write out information in format for doxygen build instructions')
    parser.add_option(
        '--sim', dest='simarch',
        help='Create an ioc with arch=SIMARCH in simulation mode')
    parser.add_option(
        '-e', action='store_true', dest='edm_screen',
        help='Try to create a set of edm screens for this module')
    parser.add_option(
        '-c', action='store_true', dest='no_check_release',
        help='Set CHECK_RELEASE to FALSE')
    parser.add_option(
        '-b', action='store_true', dest='no_substitute_boot',
        help='Don\'t substitute .src file to make a .boot file, copy it and '\
        ' create an envPaths file to load')
    parser.add_option(
        '--build-debug', action='store_true', dest='build_debug',
        help='Enable debug build of IOC')

    # parse arguments
    (options, args) = parser.parse_args()
    if len(args) != 1:
        parser.error(
            '*** Error: Incorrect number of arguments - '
            'you must supply one input file (.xml)')

    # define parameters
    if options.debug:
        debug = True
    else:
        debug = False
    if options.DbOnly:
        DbOnly = True
    else:
        DbOnly = False

    # setup the store
    xml_file = args[0]
    store = Store(debug = debug, DbOnly = DbOnly, doc = options.doc)
    if options.debug:
        print '--- Parsing %s ---' % xml_file
    
    # read the xml text for the architecture
    xml_text = open(xml_file).read()
    xml_root = xml.dom.minidom.parseString(xml_text)
    components = [n
        for n in xml_root.childNodes if n.nodeType == n.ELEMENT_NODE][0]
    if options.simarch is not None:
        store.architecture = patch_arch(options.simarch)
        store.simarch = store.architecture
    else:
        store.architecture = patch_arch(str(components.attributes['arch'].value))
        store.simarch = None
    
    # Now create a new store, loading the release file from this xml file
    store.New(xml_file)
    store.iocbuilder.SetSource(os.path.realpath(xml_file))

    # create iocbuilder objects from the xml text
    store.iocbuilder.includeXml.instantiateXml(xml_text)

    if options.doc:
        iocpath = options.doc
    elif DbOnly:
        iocpath = os.path.abspath(".")
        if options.simarch:
            store.iocname += '_sim'
    else:
        # write the iocs
        root = os.path.abspath(options.out)
        iocpath = os.path.join(root, store.iocname)
        if options.simarch:
            iocpath += '_sim'
#            store.iocbuilder.SetEpicsPort(6064)

    substitute_boot = not options.no_substitute_boot
    if store.architecture == "win32-x86":
        substitute_boot = False
    if debug:
        print "Writing ioc to %s" % iocpath
    store.iocbuilder.WriteNamedIoc(iocpath, store.iocname, check_release = not options.no_check_release,
        substitute_boot = substitute_boot, edm_screen = options.edm_screen, build_debug = options.build_debug)
    if debug:
        print "Done"

    # Check for README in same directory as source XML
    copy_readme(xml_file, iocpath, debug)


def readme_exists(xml_file, debug):
    readme_path = xml_file.replace(".xml", "_README.md")
    if os.path.exists(readme_path):
        if debug:
            print("Found README at {path}".format(path=readme_path))
        return readme_path
    else:
        if debug:
            print("No README found")
        return None


def copy_readme(xml_file, iocpath, debug):
    # Check for README
    source_readme_path = readme_exists(xml_file, debug)
    if source_readme_path is not None:
        if debug:
            print("Copying README to {0}".format(iocpath))
        destination_readme_path = "{iocpath}/README.md".format(iocpath=iocpath)
        shutil.copyfile(source_readme_path, destination_readme_path)



if __name__=='__main__':
    # Pick up containing IOC builder
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    sys.path.append(root)
    from pkg_resources import require
    require('dls_environment')
    require('dls_dependency_tree')
    require('dls_edm')
    main()
