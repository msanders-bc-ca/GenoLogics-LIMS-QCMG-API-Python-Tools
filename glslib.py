'''
    Python3 utility functions for Genologics REST API.
    
    This module is developed & tested in Python 3.2. It is possible that it may
    work with earlier 3.x but that would be accidental. Additionally,
    absolutely no guarantee could be offered that future development would 
    preserve such accidental backwards-compatibility.

    This module exposes ElementTree-style interface for xml operations. 
    
    This module uses logging and has one module-level Logger named "__name__".
    Assuming this module is used as part of package "glsapi", this logger may
    be accessed from elsewhere using logging.getLogger('glsapi.glslib')
    
    Copyright 2011,2012,2013 Conrad Leonard http://qcmg.org/
    
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
import os
import os.path
import sys
import logging
import base64
import urllib.request, urllib.error
import re
import xml.etree.ElementTree as etree
from copy import deepcopy


class GlslibException(Exception):
    pass

# It is the responsibility of code that imports this module to add handlers
# e.g. glslib.logger.addHandler(logging.StreamHandler())
logger = logging.getLogger(__name__)
logger.setLevel(logging.WARN)


_VERSION = (1, 5, 1)
_APIVERSION = None
_BASEURI = None
_AUTHSTR = None
_GLSFTPAUTH = None
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
_NSREV = { v:k for k, v in _NSMAP.items() }
# Deal with ns prefixes in ElementTree by registering in _namespace_map
etree._namespace_map.update(_NSREV)
    
MSGBADCREDENTIALFILEFORMAT = '''
Credentials file must contain only lines of the form
<servername>:::<user>:::<password>'''
MSGBADAUTHFILEPERMS = '''
'%s must have permissions = 600'''
MSGBADAUTHDIRPERMS = '''
%s must have permissions = 700'''
MSGNOCREDENTIALSFOUND = '''
Credentials for %s not found.'''
MSGUNSUPPORTEDMETHOD = '''
Unsupported method "%s"'''
MSGBADTAGFORMAT = '''
'Tag "%s" is not in etree format {namespace}local'''
MSGBATCHMETHODNOTIMPLEMENTED = '''
API version detected is < 13. Batch methods not implemented.'''


def version():
    return '.'.join(map(str, _VERSION))


def set_debug(debug=True):
    '''
    Toggle logger level between DEBUG and WARN
    '''
    if debug:
        logger.setLevel(logging.DEBUG)
    else:
        logger.setLevel(logging.WARN)
    

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

    
def Element(tag, _text_=None, **extra):
    '''
    Wrapper for etree.Element() adds text via optional 2nd arg. 
    GLS-specific tags can be specified like "prefix:local" 
    instead of standard ElementTree-style "{namespace}local"
    '''
    tag = _expand_tag(tag)
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
    se = etree.SubElement(parent, tag, **extra)
    se.text = _text_
    return se


# Pretty-print element tree - not native in ElementTree but
# a convenient (and slow) fallback using standard library: 
def pprint(elem):
    from xml.dom.minidom import parseString
    txt = etree.tostring(elem)
    print(parseString(txt).toprettyxml()) 


def add_ud_elems(parent, udts=None, udfs=None):
    '''
    Add userdefined elements to parent elem.
    
    'parent' is parent element
    'udts' is a dictionary of dictionaries: {udtname:{udfname:value}}
    'udfs' is a dictionary mapping udf names to values
    '''
    udts = udts or {}
    udfs = udfs or {}
    for udtname, typeudfs in udts.items():
        type_ = SubElement(parent, 'udf:type', name=udtname)
        for k, v in typeudfs.items():
            if v: # API doesn't allow udf tags with empty text 
                SubElement(type_, 'udf:field', v, name=k) 
    for k, v in udfs.items():
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
    logger.debug(etree.tostring(prjelem, 'unicode'))
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
    logger.debug(etree.tostring(contelem, 'unicode'))
    return contelem


def make_sample_elem(nametxt, project, container, locationtxt, 
                     datercv=None, udts=None, udfs=None):
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
    logger.debug(etree.tostring(smpelem, 'unicode'))
    return smpelem


#----------------------------------------------
# These functions are for setting/getting data
#----------------------------------------------
def register(servername='qcmg-gltest', authfile='~/.geneus/gl_credentials.cfg'):
    '''
    Register service URI and authentication details from a secure file.
    The file must have lines of the form: 
    # comment
    <servername>:::<user>:::<password>

    The file must have permissions *600 and its directory permissions *700.
    The 'servername' argument must match a <servername> entry in the file.
    '''
    global _BASEURI, _AUTHSTR
    authfile = os.path.expanduser(authfile)
    authdir = os.path.dirname(authfile)
    dirmode = oct(os.stat(authdir).st_mode)[-3:]
    if not dirmode.endswith('700'):
        raise GlslibException(MSGBADAUTHDIRPERMS % authdir)
    fmode = oct(os.stat(authfile).st_mode)[-3:]
    if not fmode.endswith('600'):
        raise GlslibException(MSGBADAUTHFILEPERMS % authfile)
    fh = open(authfile)
    server, match = None, None
    for line in fh:
        try:
            if not line.startswith('#') and line.strip():
                (server, user, pwd) = line.strip().split(':::')
        except:
            logger.error(MSGBADCREDENTIALFILEFORMAT)
        if server == servername:
            match = (server, user, pwd)
            break
    if not match:
        raise GlslibException(MSGNOCREDENTIALSFOUND % servername)
    _BASEURI = 'http://' + server + ':8080/api' #here, _BASEURI is versionless
    authbytes = base64.b64encode(bytes('%s:%s' % (user, pwd), 'ascii'))
    _AUTHSTR = str(authbytes, 'ascii')
    set_api_version()
    
    
def set_api_version():
    '''
    Called at the end of register() to set _APIVERSION, and append major
    version to _BASEURI
    '''
    global _APIVERSION, _BASEURI
    ver = get('') # _BASEURI is versionless at this point
    version = ver.find('version')
    major = version.get('major')
    minor = version.get('minor')
    _APIVERSION = '.'.join([major, minor])
    _BASEURI = os.path.join(_BASEURI, major)
    
    
def glsrequest(uri, method, data=None):
    '''
    Returns xml node tree as Element instance.
    
    'uri' may be absolute or relative to _BASEURI.
    'method' in ('GET', 'POST', 'PUT')
    'data' can be a string or Element instance
    '''
    if method not in {'GET', 'POST', 'PUT'}:
        raise GlslibException(MSGUNSUPPORTEDMETHOD % method)
    if not uri.startswith(_BASEURI):
        uri = _BASEURI.rstrip('/') + '/' + uri.lstrip('/')
    request = urllib.request.Request(uri)
    request.add_header("Authorization", "Basic %s" % _AUTHSTR)
    if etree.iselement(data):
        # tostring generates bytestring (as required for data)
        data = etree.tostring(data)
        request.add_header('Content-Type', 'application/xml')
    request.add_data(data)
    request.get_method = lambda: method
    msg = '%s %s\n%s\n%s' % (request.get_method(), 
                             request.get_full_url(),
                             request.headers, 
                             data.decode('utf-8') if data else '')
    logger.debug(msg)
    try:
        r = urllib.request.urlopen(request)
        return etree.XML(r.read())
    except urllib.error.HTTPError as httperr:
        logger.error(httperr.read())
        raise
    except urllib.error.URLError as urlerr:
        logger.error(request.get_full_url())
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
            raise GlslibException(MSGBADTAGFORMAT % resource.tag)
    return glsrequest(listuri, 'POST', resource)


def batch_retrieve(uris):
    '''
    Return list of artifacts for batch of uri's.
    API version >= v1.r13 only
    
    'uris' is any iterable of uris.
    '''
    major, minor = [ int(i.lstrip('vr')) for i in _APIVERSION.split('.') ]
    if major == 0 or (major == 1 and minor < 13):   
        raise GlslibException(MSGBATCHMETHODNOTIMPLEMENTED)
    payload = Element('ri:links')
    for uri in uris:
        SubElement(payload, 'link', uri=uri, rel='artifacts')
    response = glsrequest('artifacts/batch/retrieve', 'POST', payload)
    return response.findall('.//{%s}artifact' % _NSMAP['art'])


def batch_update(artifacts):
    '''
    Batch update supplied list of artifacts
    API version >= v1.r13 only
    
    'artifacts' is any iterable of artifacts.
    '''
    major, minor = [ int(i.lstrip('vr')) for i in _APIVERSION.split('.') ]
    if major == 0 or (major == 1 and minor < 13):        
        raise GlslibException(MSGBATCHMETHODNOTIMPLEMENTED)
    payload = Element('art:details')
    for art in artifacts:
        # lxml elements can be in only one tree at a time.
        # deepcopy here will preserve namespace declarations in artifact tag
        payload.append(deepcopy(art))
    response = glsrequest('artifacts/batch/update', 'POST', payload)
    updated = response.findall('link')
    for u in updated:
        logger.info('%s %s' % ("Updated", u.get('uri')))
