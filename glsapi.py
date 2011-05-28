'''
    Python utility functions for Genologics REST API.

    This module exposes ElementTree-style interface for xml operations. 
    By default it uses lxml.etree, and ElementTree itself if lxml is not 
    available.    
    
    Copyright 2011 Conrad Leonard http://qcmg.org/
    
    This library is free software: you can redistribute it and/or
    modify it under the terms of the GNU Lesser General Public
    License as published by the Free Software Foundation, either
    version 3 of the License, or (at your option) any later version.
    
    This library is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
    Lesser General Public License for more details.
    
    You should have received a copy of the GNU Lesser General Public
    License along with this library.  If not, see <http://www.gnu.org/licenses/>
'''
import sys
import base64
import urllib2
import re

_LXML = True

try:
    from lxml import etree 
    print("running with lxml.etree")
except ImportError:
    _LXML = False
    try:
        # Standard library ElementTree (Python 2.5+) 
        import xml.etree.ElementTree as etree
        print("running with ElementTree on Python 2.5+")
    except ImportError:
        try:
            # Normal ElementTree install
            import elementtree.ElementTree as etree
            print("running with ElementTree")
        except ImportError:
          sys.exit("Failed to import ElementTree from any known place")

_VERSION = (1, 0, 2)
_DEBUG = False
_BASEURI = None
_AUTHSTR = None
_NSPATTERN = re.compile(r'(\{)(.+?)(\})')

_NSMAP = {
'artgr':'http://genologics.com/ri/artifactgroup',
'art':'http://genologics.com/ri/artifact',
'cnf':'http://genologics.com/ri/configuration',
'con':'http://genologics.com/ri/container',
'ctp':'http://genologics.com/ri/containertype',
'exc':'http://genologics.com/ri/exception',
'file':'http://genologics.com/ri/file',
'lab':'http://genologics.com/ri/lab',
'perm':'http://genologics.com/ri/permissions',
'prc':'http://genologics.com/ri/process',
'prj':'http://genologics.com/ri/project',
'prop':'http://genologics.com/ri/property',
'prx':'http://genologics.com/ri/processexecution',
'ptp':'http://genologics.com/ri/processtype',
'res':'http://genologics.com/ri/researcher',
'rgt':'http://genologics.com/ri/reagent',
'ri':'http://genologics.com/ri',
'rtp':'http://genologics.com/ri/reagenttype',
'smp':'http://genologics.com/ri/sample',
'udf':'http://genologics.com/ri/userdefined',
'ver':'http://genologics.com/ri/version',
}
_NSREV = dict([(v, k) for k, v in _NSMAP.iteritems()])
if not _LXML:
    # Deal with ns prefixes in ElementTree by registering in _namespace_map
    etree._namespace_map.update(_NSREV)


def version():
    return '.'.join(map(str, _VERSION))


#------------------------------------------------------
# These functions are for working with elements (nodes)
#------------------------------------------------------
def _expand_tag(tag):
    '''
    For prefixes in _NSMAP rewrite:
    "prefix:local" -> etree format "{namespace}local"
    '''
    tsplit = tag.split(':')
    if len(tsplit) == 2 and tsplit[0] in _NSMAP.keys():
        tag = '{%s}%s' % (_NSMAP[tsplit[0]], tsplit[1])
    return tag


def _get_nsmap(tag):
    '''
    Return nsmap for tag "{namespace}local"
    '''
    m = _NSPATTERN.match(tag)
    if m:
        ns = m.group(2)
        return {_NSREV[ns]:ns}
    else:
        return None
    
    
def Element(tag, _text_=None, **extra):
    '''
    Wrapper for etree.Element() adds text via optional 2nd arg. 
    GLS-specific tags can be specified like "prefix:local" 
    instead of standard ElementTree-style "{namespace}local"
    '''
    tag = _expand_tag(tag)
    if _LXML:
        extra['nsmap'] = _get_nsmap(tag)
    e = etree.Element(tag, **extra)        
    e.text = _text_
    return e


def SubElement(parent, tag, _text_=None, **extra):
    '''
    Wrapper for etree.SubElement() adds text via optional 3rd arg.
    GLS-specific tags can be specified like "prefix:local" 
    instead of standard ElementTree-style "{namespace}local"
    '''
    tag = _expand_tag(tag)
    if _LXML:
        extra['nsmap'] = _get_nsmap(tag)
    se = etree.SubElement(parent, tag, **extra)
    se.text = _text_
    return se


# Pretty-print element tree
if _LXML:
    def pprint(elem):
        print etree.tostring(elem, pretty_print=True)
else:
    # A convenient but slow-ish fallback using standard library: 
    def pprint(elem):
        from xml.dom.minidom import parseString
        txt = etree.tostring(elem)
        print parseString(txt).toprettyxml() 
        

def set_elem_text(parent, tag, newvalue, insertbefore=None, **attrib):
    '''
    Find element specified by tag & attributes, update text.
    
    Returns parent element. If specified element is not found but 
    insertbefore is specified, create new element with the specified tag, 
    attributes & text at that location.
    '''
    elems = parent.findall(tag)
    for k, v in attrib.iteritems():
        copy = elems[:] # So we don't modify list we're iterating over
        for e in copy:
            if (not e.get(k)) or (e.get(k) != v):
                elems.remove(e)
    if len(elems) == 0:
        if insertbefore is not None:
            ibelem = parent.find(insertbefore.tag)
            if ibelem is None:
                raise Exception('Insert location %s not found' % 
                                                            (insertbefore.tag))
            pos = parent.getchildren().index(ibelem)
            parent.insert(pos, Element(tag, newvalue, **attrib))
        else:
            raise Exception('No match & location for new element not specified')
    elif len(elems) == 1:
        elems[0].text = newvalue
    else:
        raise Exception('Multiple tags match')
    return parent


def add_ud_elems(parent, udts=None, udfs=None):
    '''
    Add userdefined elements to parent elem.
    
    'parent' is parent element
    'udts' is a dictionary of dictionaries: {udtname:{udfname:value}}
    'udfs' is a dictionary mapping udf names to values
    '''
    if not udts:
        udts = {}
    if not udfs:
        udfs = {}
    for udtname, typeudfs in udts.iteritems():
        type_ = SubElement(parent, 'udf:type', name=udtname)
        for k, v in typeudfs.iteritems():
            if v: # API doesn't allow udf tags with empty text 
                SubElement(type_, 'udf:field', v, name=k) 
    for k, v in udfs.iteritems():
        if v: # API doesn't allow udf tags with empty text
            SubElement(parent, 'udf:field', v, name=k)
    return parent


def make_project_elem(nametxt, researcher, opendate=None, udts=None, udfs=None):
    '''
    Return valid Element representation of a project.
    
    'nametxt' is project name
    'researcher is integer researcher ID
    'opendate' is in YYYY-MM-DD format
    'udts' is a dictionary of dictionaries: {udtname:{udfname:value}}
    'udfs' is a dictionary mapping udf names to values
    '''
    prjelem = Element('prj:project')
    SubElement(prjelem, 'name', nametxt)
    if opendate:
        SubElement(prjelem, 'open-date', opendate)
    SubElement(prjelem, 'researcher', 
               uri='%s/researchers/%s'%(_BASEURI, str(researcher)))
    add_ud_elems(prjelem, udts, udfs)
    if _DEBUG:
        pprint(prjelem)
    return prjelem


def make_container_elem(nametxt, contype, udts=None, udfs=None):
    '''
    Return valid Element representation of an empty container.
    
    'nametxt' is container name
    'type' is integer container type, e.g. 2=tube.
    'udts' is a dictionary of dictionaries: {udtname:{udfname:value}}
    'udfs' is a dictionary mapping udf names to values
    '''
    contelem = Element('con:container')
    SubElement(contelem, 'name', nametxt)
    SubElement(contelem, 'type', 
               uri='%s/containertypes/%s' % (_BASEURI, str(contype)))
    add_ud_elems(contelem, udts, udfs)
    if _DEBUG:
        pprint(contelem)
    return contelem


def make_sample_elem(nametxt, project, container, locationtxt, datercv=None, 
                     udts=None, udfs=None):
    '''
    Return valid Element representation of a sample.
    
    'nametxt' is sample name
    'project' is LIMSID of project
    'container' is LIMSID of an empty container
    'locationtxt' is location in container
    'datercv' is date received
    'udts' is a dictionary of dictionaries: {udtname:{udfname:value}}
    'udfs' is a dictionary mapping udf names to values
    '''
    smpelem = Element('smp:samplecreation')
    SubElement(smpelem, 'name', nametxt)
    if datercv:
        SubElement(smpelem, 'date-received', datercv)
    SubElement(smpelem, 'project', uri='%s/projects/%s' % (_BASEURI, project))
    add_ud_elems(smpelem, udts, udfs)
    locelem = SubElement(smpelem, 'location')
    SubElement(locelem, 'container', limsid=container)
    SubElement(locelem, 'value', locationtxt)
    if _DEBUG:
        pprint(smpelem)
    return smpelem


#----------------------------------------------
# These functions are for setting/getting data
#----------------------------------------------
def register_service_details(baseuri, key, password):
    '''
    Registers service URI and authentication details.
    
    Client code must call this (once) before using set/get methods.
    '''
    global _BASEURI, _AUTHSTR 
    _BASEURI = baseuri
    _AUTHSTR = base64.encodestring('%s:%s' % (key, password)).replace('\n', '')
    
    
def glsrequest(uri, method, data=None):
    '''
    Returns xml node tree as Element instance.
    
    'uri' may be absolute or relative to _BASEURI.
    'method' in ('GET', 'POST', 'PUT')
    'data' can be a string or Element instance
    '''
    if method not in ('GET', 'POST', 'PUT'):
        raise Exception('Unsupported method "%s"' % (method))
    if not uri.startswith(_BASEURI):
        uri = _BASEURI.rstrip('/') + '/' + uri.lstrip('/')
    request = urllib2.Request(uri)
    request.add_header("Authorization", "Basic %s" % _AUTHSTR)
    if etree.iselement(data):
        data = etree.tostring(data)
        request.add_header('Content-Type', 'application/xml')
    request.add_data(data)
    request.get_method = lambda: method
    if _DEBUG:
        print request.get_method(), request.get_full_url(), request.headers, data
    try:
        r = urllib2.urlopen(request)
        return etree.XML(r.read())
    except urllib2.HTTPError, httperr:
        print '\n', httperr.read(), '\n'
        raise
    except urllib2.URLError, urlerr:
        print '\n', request.get_full_url(), '\n'
        raise
    
    
def get(uri):
    '''
    Return Element representation of resource at uri.
    '''
    return glsrequest(uri, 'GET')
    
    
def update(resource):
    '''
    PUT an updated version of resource to the system.
    
    'resource' must be a valid Element representation of existing resource.
    'resource' must be a full representation. Missing elements are deleted.
    '''
    return glsrequest(resource.get('uri'), 'PUT', resource)


def add_new(resource, listuri=None):
    '''
    POST a new instance of a resource to the system.
    
    'resource' must be a valid Element representation, including tag
     specified like '{namespace}local' 
    '''
    # If listuri not specified, try to guess it by pluralizing tag namespace
    if not listuri:
        try:
            ns = _NSPATTERN.match(resource.tag).group(2)
            listuri = '/%ss' % (ns.split('/')[-1])
        except AttributeError:
            raise Exception('Tag "%s" is not in etree format {namespace}local' 
                            % resource.tag)
    return glsrequest(listuri, 'POST', resource)
