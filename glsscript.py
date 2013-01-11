'''
    Python3 script classes for Genologics REST API.
    
    This module is part of the glslib package and locally imports glslib.py 
    
    This module is developed & tested in Python 3.2. It is possible that it may
    work with earlier 3.x but that would be accidental. Additionally,
    absolutely no guarantee could be offered that future development would 
    preserve such accidental backwards-compatibility.
        
    Copyright 2012,2013 Conrad Leonard http://qcmg.org/
    
    This library is free software: you can redistribute it and/or
    modify it under the terms of the GNU Lesser General Public
    License as published by the Free Software Foundation, either
    version 3 of the License, or (at your option) any later version.
    
    This library is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
    Lesser General Public License for more details.
    
    You should have received a copy of the GNU Lesser General Public
    License along with this library. If not, see <http://www.gnu.org/licenses/>
'''
import sys
import argparse
import os.path
import logging
import subprocess
import shlex
import smtplib
from io import StringIO
from email.mime.text import MIMEText
from socket import gethostname
from datetime import datetime
from base64 import b64decode
from urllib.parse import urlparse
from . import glslib

MAILTO = ['c.leonard@imb.uq.edu.au',]
#MAILTO = ['QCMG-InfoTeam@imb.uq.edu.au',]
MAILFROM = 'c.leonard2@uq.edu.au'
LOGFORMAT = '[%(levelname)s]\t%(name)s\t%(message)s'
LOGMETHODMAP = {
'DEBUG':logging.Logger.debug,
'INFO':logging.Logger.info,
'WARN':logging.Logger.warn,
'ERROR':logging.Logger.error,
'CRITICAL':logging.Logger.critical
}
MSGBADLOGMETHOD = '''
logmethod must be one of %s
Setting log method to default of ERROR''' % ', '.join(list(LOGMETHODMAP.keys()))
MSGNOLOPTIONDEFINED = '''
"l:" option is required by EPPScript to specify processuri, but supplied 
opstring definition does not contain it. Appending "l:" option to optstring.'''
MSGNOLOPTIONSUPPLIED = '''
No "-l" option supplied at command line'''
MSGBADPROCESSURI = '''
Supplied value of "-l" doesn't appear to be a uri''' 


class ScriptException(Exception):
    pass


class Script(object):
    '''
    ==Base class for a CLI script==
    '''
    def __init__(self, description, logfile=None):
        '''
        Constructor for Script class.
        
        description    Description of script
        logfile        Name of logfile (default=None)
        '''
        self.parser = argparse.ArgumentParser(description=description)
        self.mailto = MAILTO
        self.mailfrom = MAILFROM
        self.scriptname = os.path.basename(sys.argv[0])
        self.logger = None
        self.logfile = logfile
        self.set_logging(logfile)
        
    def usage(self):
        '''
        Output help string from self.parser using self.logger
        '''
        self.logger.info(self.parser.format_usage())
        
    def set_logging(self, logfile):
        '''
        Set self.logfile, self.logger, add handlers and set formats
        '''
        self.logfile = logfile
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.DEBUG)
        self.logger.addHandler(logging.StreamHandler())
        if logfile is not None:
            self.logger.addHandler(logging.FileHandler(logfile))
        fm = logging.Formatter(LOGFORMAT)
        for h in self.logger.handlers:
            h.setLevel(logging.DEBUG)
            h.setFormatter(fm)
            
    def parse_args(self, force=False):
        '''
        Wrapper around self.parser method.
        Set self.<attribute> from dictionary of arguments.
        When force is False (default), raise AttributeError if there is an 
        existing attribute of the same name. When force is True, always set the 
        attribute.
        '''
        # Capture stdout, stderr because on failure (and also on displaying 
        # help message) parse_args() just prints a message and dumps you right
        # out with SystemExit. We want to keep the message and exit cleanly. 
        sys.stdout.flush()
        sys.stderr.flush()
        oldout, olderr = sys.stdout, sys.stderr
        with StringIO() as capture:
            sys.stdout = sys.stderr = capture
            try:
                args = vars(self.parser.parse_args())
            except SystemExit as e:
                # -h, --help also raises SystemExit, but with code = 0
                loglevel = 'INFO' if e.code == 0 else 'ERROR'
                self.exit(capture.getvalue(), loglevel, 2)
            for k, v in args.items():
                if hasattr(self, k) and not force:
                    raise AttributeError('%s instance already has attribute %s' 
                                         % (self.__class__, k))
                else:
                    setattr(self, k, v)
            sys.stdout, sys.stderr = oldout, olderr
        
    def shell_execute(self, cmd, split=True, stderrexit=True, email=False, 
                      **kwargs):
        '''
        Wrapper around call to subprocess.Popen(args, kwargs).
        Catch exceptions and anything in stderr and exit cleanly, otherwise
        return stdout.
        
        cmd            Command line
        split          Use shlex.split to split cmd (default=True)
        stderrexit     Exit if stderr (default=True) else just log warning
        email          Email on any exit (default=False)
        **kwargs       keyword args supplied to subprocess.Popen
        '''
        self.logger.info(cmd)
        args = shlex.split(cmd) if split else cmd
        kwargs['stderr'] = subprocess.PIPE
        try:
            p = subprocess.Popen(args, **kwargs)
        except Exception as e:
            self.exit(e, 'CRITICAL', 2, email)
        stdout, stderr = p.communicate()     
        if stderr:
            if stderrexit:
                self.exit(stderr.decode('ascii'), 'CRITICAL', 3, email)
            else:
                self.logger.warn(stderr.decode('ascii'))
        return stdout

    def email(self, subject, msg, mailto=None, mailfrom=None):
        '''
        Send email.
        
        mailto    List of recipients (default=self.mailto=<module>.MAILTO)
        mailfrom  Sender (default=self.mailfrom=<module>.MAILFROM)
        '''
        mailto = mailto or self.mailto
        mailfrom = mailfrom or self.mailfrom
        if not mailfrom:
            self.logger.warn('No email sender specified. Mail not sent.')
        if not mailto:
            self.logger.warn('No email recipients specified. Mail not sent.')
        if mailfrom and mailto:
            msg = MIMEText(msg)
            msg['Subject'] = subject
            s = smtplib.SMTP('localhost')
            s.sendmail(mailfrom, mailto, msg.as_string())
            
    def _preexit(self, message='', logmethod='INFO', exitcode=0, email=False):
        '''
        Helper for exit() to contain all the stuff before actually exiting,
        enabling re-use by derived classes.
        '''
        l = LOGMETHODMAP.get(logmethod)
        if not l:
            self.logger.warn(MSGBADLOGMETHOD)
            l = logging.Logger.error
        l(self.logger, message)
        status = "SUCCESS" if exitcode == 0 else "FAILURE"
        if email:
            subject = '%s %s %s' % (gethostname(), self.scriptname, status)
            message += '\n%s\n' % datetime.today().strftime('%Y.%m.%d:%H:%M:%S')
            if self.logfile:
                message += '\nlog at %s\n' % os.path.abspath(self.logfile)
            self.email(subject, message)

    def exit(self, message='', logmethod='INFO', exitcode=0, email=False):
        '''
        Log message, email message if required, and sys.exit. This method 
        should be used by Script methods instead of bare sys.exit().
        
        logmethod   [DEBUG|INFO|WARN|ERROR|CRITICAL]
        '''
        self._preexit(message, logmethod, exitcode, email)
        sys.exit(exitcode)
        
        
class GlsScript(Script):
    '''
    ==Class for a CLI script using glslib==
    '''
    def __init__(self, description, logfile=None, servername=None, 
                 authfile='~/.geneus/gl_credentials.cfg'):
        '''
        Constructor for GlsScript class. -d, --debug optional argument is added
        to parser
        
        description    Description of how to use the script
        logfile        Name of logfile (default=None)
        servername     Name of GLS server (default=None, requires explicit call
                       to register())
        authfile       Location of GLS authfile
                       (default='~/.geneus/gl_credentials.cfg')  
        '''
        Script.__init__(self, description, logfile)
        self.glslib = glslib
        self.servername = servername
        self.authfile = os.path.expanduser(authfile)
        # configure logging for self.glslib.logger
        self.set_glslib_logging()
        self.parser.add_argument('-d', '--debug',
                                 dest='DEBUG', 
                                 action='store_true',
                                 default=False,
                                 help='Turn on debugging output from glslib')
        if self.servername:
            self.glslib.register(self.servername, self.authfile)

    def parse_args(self, force=False):
        '''
        Wrapper around self.parser.parse_args()
        '''
        Script.parse_args(self, force)
        if self.DEBUG:
            self.glslib.set_debug(True)
        
    def set_glslib_logging(self):
        '''
        Add handlers from self.logger to Logger in self.glslib
        '''
        glslib_logger = logging.getLogger('%s.glslib' % __package__)
        for handler in self.logger.handlers:
            glslib_logger.addHandler(handler)
        
    def register(self, servername=None, 
                 authfile='~/.geneus/gl_credentials.cfg'):
        '''
        Set self.servername and self.authfile. Register self.glslib to 
        self.servername using self.authfile. 
        
        servername    Name of GLS server. If not supplied, defaults first to
                      self.servername, then to 'qcmg-gltest.imb.uq.edu.au'
        authfile      Location of GLS authfile 
                      (default='~/.geneus/gl_credentials.cfg')
        '''
        self.servername = (servername or
                           self.servername or
                           'qcmg-gltest.imb.uq.edu.au')
        self.authfile = os.path.expanduser(authfile)
        self.glslib.register(self.servername, self.authfile)
        
        
class EPPScript(GlsScript):
    '''
    ==Class for an EPP script using glslib==
    '''
    
    def __init__(self, description, logfile=None, servername=None,
                 authfile='~/.geneus/gl_credentials.cfg'):
        '''
        Constructor for EPP script. Processuri is added to parser as first 
        positional argument.
        
        description    Description of how to use the script
        logfile        Name of logfile (default=None)
        servername     Name of GLS server (default=None, requires explicit call
                       to register())
        authfile       Location of GLS authfile 
                       (default='~/.geneus/gl_credentials.cfg')
        '''
        GlsScript.__init__(self, description, logfile, servername, authfile)
        self.processuri = None
        self.parser.add_argument('processuri', 
                            help='processuri of process invoking EPPScript')
        
    def register(self, servername=None, 
                 authfile='~/.geneus/gl_credentials.cfg'):
        '''
        Set self.servername and self.authfile. Register self.glslib to 
        self.servername using self.authfile. 
        
        servername    Name of GLS server. If not supplied, defaults first to
                      machine implied in self.processuri, then to 
                      '10.160.72.33'
        authfile      Location of GLS authfile 
                      (default='~/.geneus/gl_credentials.cfg')
        '''
        if servername:
            self.servername = servername
        elif hasattr(self, 'processuri') and self.processuri:
            netloc = self.servername = urlparse(self.processuri).netloc
            self.servername = netloc.split(':')[0]
        else:
            self.servername = '10.160.72.33'
        self.authfile = os.path.expanduser(authfile)
        self.glslib.register(self.servername, self.authfile)
            
    def _preexit(self, message='', logmethod='INFO', exitcode=0, email=False):
        '''
        Call Script._preexit, then if exitcode !=0 or logmethod in {'ERROR', 
        'CRITICAL'}, add error flags to LIMS outputs
        '''
        Script._preexit(self, message, logmethod, exitcode, email)
        if exitcode != 0 or logmethod in {'ERROR', 'CRITICAL'}:
            datestr = datetime.today().strftime('%Y-%m-%d')
            timestr = datetime.today().strftime('%Y-%m-%d:%H:%M:%S')
            # prepend some helpful info to message
            preamble = '%s -- %s\n' % (gethostname(), timestr)
            # sanitize command line 
            authbytes = b64decode(bytes(self.glslib._AUTHSTR,'ascii'))
            pwd = str(authbytes,'ascii').split(':')[1]
            commandline = ' '.join(sys.argv).replace(pwd, '****')
            preamble += '%s\n' % commandline
            message = preamble + message
            serviceuri = self.processuri.rsplit('/',2)[0]
            process = glslib.get(self.processuri)
            notestr = 'Oops...\r\n%s' % message
            outputuris = { o.get('uri') for o in process.findall('.//output') }
            if outputuris:
                outputs = glslib.batch_retrieve(outputuris)
                for output in outputs:
                    gflag = output.find('artifact-flag[@typeID="-1"]')
                    if gflag is None:
                        gflag = glslib.SubElement(output, 'artifact-flag', None,
                                                  name='External Program Error',
                                                  typeID='-1')
                        creator = glslib.SubElement(gflag, 'creator', None,
                                            uri='%s/researchers/1' % serviceuri)
                        lmdate = glslib.SubElement(gflag, 
                                            'last-modified-date', datestr)
                        note = glslib.SubElement(gflag, 'note', notestr)
                    else:
                        gflag.find('note').text += '\r\n' + notestr
                        gflag.find('last-modified-date').text = datestr
                glslib.batch_update(outputs)            
        
