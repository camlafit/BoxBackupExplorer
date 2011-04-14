#!/usr/bin/env python
# -*- coding: UTF-8 -*-
#
#       bbexplorer.cgi - Webfrontend to Box Backup
#
#       Copyright (c) 2009 joonis new media
#       Author: Thimo Kraemer <thimo.kraemer@joonis.de>
#
#       This program is free software; you can redistribute it and/or modify
#       it under the terms of the GNU General Public License as published by
#       the Free Software Foundation; either version 2 of the License, or
#       (at your option) any later version.
#       
#       This program is distributed in the hope that it will be useful,
#       but WITHOUT ANY WARRANTY; without even the implied warranty of
#       MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#       GNU General Public License for more details.
#       
#       You should have received a copy of the GNU General Public License
#       along with this program; if not, write to the Free Software
#       Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
#       MA 02110-1301, USA.
#


#################################################
# Configuration
#

# Path to bbackupquery
path_bbquery = '/usr/sbin/bbackupquery'

# Path to sudo
path_sudo = '/usr/bin/sudo'

# URL to images
path_images = 'images'

# Authorized remote users
# [] -> All users, except anonymous
# ['backup', 'admin'] -> User backup and admin
# [None] -> Anonymous (For testing purposes only!)
auth_users = []

# Authorized remote hosts
# [] -> All hosts
# ['192.168.0.44', '192.168.0.87'] -> Host 192.168.0.44 and 192.168.0.87 only
auth_hosts = []

# Blocksize on storage server
blocksize = 4096

#
# End of configuration
#################################################


import cgi, cgitb
import os, sys
import subprocess
import re
import md5
import datetime
import tarfile
import tempfile

# Globals
script_path = os.path.realpath(sys.argv[0])
script_user = os.stat(script_path)[4]
path_temp = os.path.join(tempfile.gettempdir(), 'boxbackup')


class Templite(object):
    """Templating engine"""
    auto_emit = re.compile('(^[\'\"])|(^[a-zA-Z0-9_\[\]\'\"]+$)')
    
    def __init__(self, template, start='${', end='}$'):
        if len(start) != 2 or len(end) != 2:
            raise ValueError('each delimiter must be two characters long')
        delimiter = re.compile('%s(.*?)%s' % (re.escape(start), re.escape(end)), re.DOTALL)
        offset = 0
        tokens = []
        for i, part in enumerate(delimiter.split(template)):
            part = part.replace('\\'.join(list(start)), start)
            part = part.replace('\\'.join(list(end)), end)
            if i % 2 == 0:
                if not part: continue
                part = part.replace('\\', '\\\\').replace('"', '\\"')
                part = '\t' * offset + 'emit("""%s""")' % part
            else:
                part = part.rstrip()
                if not part: continue
                if part.lstrip().startswith(':'):
                    if not offset:
                        raise SyntaxError('no block statement to terminate: ${%s}$' % part)
                    offset -= 1
                    part = part.lstrip()[1:]
                    if not part.endswith(':'): continue
                elif self.auto_emit.match(part.lstrip()):
                    part = 'emit(%s)' % part.lstrip()
                lines = part.splitlines()
                margin = min(len(l) - len(l.lstrip()) for l in lines if l.strip())
                part = '\n'.join('\t' * offset + l[margin:] for l in lines)
                if part.endswith(':'):
                    offset += 1
            tokens.append(part)
        if offset:
            raise SyntaxError('%i block statement(s) not terminated' % offset)
        self.__code = compile('\n'.join(tokens), '<templite %r>' % template[:20], 'exec')

    def render(self, __namespace=None, **kw):
        """
        renders the template according to the given namespace. 
        __namespace - a dictionary serving as a namespace for evaluation
        **kw - keyword arguments which are added to the namespace
        """
        namespace = {}
        if __namespace: namespace.update(__namespace)
        if kw: namespace.update(kw)
        namespace['emit'] = self.write
        
        __stdout = sys.stdout
        sys.stdout = self
        self.__output = []
        eval(self.__code, namespace)
        sys.stdout = __stdout
        return ''.join(self.__output)
    
    def write(self, *args):
        for a in args:
            self.__output.append(str(a))


class CgiAccess(object):
    """Main CGI application"""
    # HTML-Template
    template = r'''Content-Type: text/html; charset=utf-8

<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN"
    "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="en" lang="en">
<head>
<meta http-equiv="Content-Type" content="text/html; charset=utf-8" />
<title>Box Backup [${dir}$]</title>
<link href="./css/main.css" rel="stylesheet" type="text/css" />
<script src="http://ajax.googleapis.com/ajax/libs/jquery/1.5/jquery.min.js" type="text/javascript"></script>
<script src="js/jquery.tablesorter.min.js" type="text/javascript"></script>
<script type="text/javascript">
<!--
function toggle(img) {
    $('tr.t_'+img.id).toggleClass('hidden');
    $('#'+img.id).toggleClass('hidden');
}
function prompt() {
    frm = document.forms.extract;
    if (frm.replace.checked) {
        result = confirm('Do you really want to replace existing destinations?');
        if (!result) {
            return false;
        }
    }
    return true;
}
$(document).ready(function() { 
    $("table").tablesorter({
        headers: { 
            // assign the secound column (we start counting zero) 
            // disable it by setting the property sorter to false 
            0: { sorter: false } 
        }
    }); 
}); 
//-->
</script>
</head>

<body>
<div id="path">
<a href="${script_name}$?dir=/">&nbsp;/</a>
${
    cdir = ''
    for item in dir.split('/')[1:]:
        if cdir: emit(' / ')
        cdir = '%s/%s' % (cdir, item)
        emit('<a href="%s?dir=%s">%s</a>' % (script_name, cdir, item))
}$
</div>

${if message['error']:}$
    <div id="error">${'<br />'.join(message['error'])}$</div>
${:endif}$
${if message['info']:}$
    <div id="info">${'<br />'.join(message['info'])}$</div>
${:endif}$

<form name="extract" action="${request_uri}$" method="post">
<input type="hidden" name="dir" value="${dir}$" />
<table border="0" cellpadding="2" cellspacing="1">
<thead>
<tr bgcolor="#dddddd">
    <th width="16" bgcolor="#ffffff">&nbsp;</th>
    <th><a href="${script_name}$?dir=${dir}$/.."><img src="${path_images}$/folder_up.gif" title="Up" alt="parent directory"/></a></th>
    <th width="340" align="left">Name</th>
    <th width="60" align="right">Size</th>
    <th width="150" align="right">Last Modified</th>
    <th>Extract</th>
    <th width="16" bgcolor="#ffffff">&nbsp;</th>
</tr>
</thead>

${if content:}$
    ${
        folded_img = ['toggle_plus.gif', 'toggle_minus.gif']
        folded_cls = ['hidden', 'visible']
        bgcolor = ['#f9f9f9', '#f0f0f0']
        switch = 0
    }$
    <tbody style="background-color: ${bgcolor[switch]}$;">
    ${for items in content:}$
        ${for item in items:}$
            ${if len(items) > 1 and item['old']:}$
                <tr id=""
                    class="t_${item['md5']}$ ${emit(folded_cls[int(item['md5'] in extracted)])}$"
                    style="background-color: ${bgcolor[switch]}$;">
            ${:else:}$
                <tr>
            ${:endif}$
            <td bgcolor="#ffffff">
                ${if len(items) > 1 and not item['old']:}$
                    <img src="${path_images}$/${emit(folded_img[int(item['md5'] in extracted)])}$"
                        id="${item['md5']}$"
                        style="cursor:pointer;"
                        onclick="toggle(this);"
                        alt="display file history" />
                ${:else:}$
                    &nbsp;
                ${:endif}$
            </td>
            <td>
                ${
                    if item['deleted']:
                        image = '_x'
                        title = 'Deleted on client'
                    elif item['remove']:
                        image = '_r'
                        title = 'Will be removed from backup as soon as marked deleted or old'
                    elif item['new']:
                        image = '_n'
                        title = 'New or currently updated'
                    else:
                        image = ''
                        title = ''
                }$
                ${if item['directory']:}$
                    <a href="${script_name}$?dir=${dir}$/${item['name']}$">
                    <img src="${path_images}$/${'folder%s.gif' % image}$" title="${title}$" alt="directory type"/>
                    </a>
                ${:else:}$
                    <img src="${path_images}$/${'file%s.gif' % image}$" title="${title}$" alt="file type"/>
                ${:endif}$
            </td>
            <td>
                ${if item['attributes']:}$
                    <img src="${path_images}$/flag_a.gif" align="right"
                        title="Has attributes stored in directory record which override attributes in backup file" alt=""/>
                ${:endif}$
                ${if item['directory']:}$
                    <a href="${script_name}$?dir=${dir}$/${item['name']}$">
                        ${item['name']}$</a>
                ${:else:}$
                    ${item['name']}$
                ${:endif}$
            </td>
            <td align="right">${item['size']}$</td>
            <td align="right">${item['modified']}$</td>
            <td align="center">
                <input type="checkbox" name="source"
                    value="${'%(file)i|%(deleted)i|%(old)i|%(id)s|%(name)s' % item}$" />
            </td>
            <td bgcolor="#ffffff">
            ${if extracted.get(item['id']) == -1:}$
                <img src="${path_images}$/failed.gif" title="Extraction failed" alt="Extraction failed" />
            ${:elif extracted.get(item['id']) == 1:}$
                <img src="${path_images}$/ok.gif" title="Extraction succeeded" alt="Extraction succeeded"/>
            ${:else:}$
                &nbsp;
            ${:endif}$
            </td>
            </tr>
        ${:endfor}$
        ${
            switch = abs(switch - 1)
        }$
    ${:endfor}$
    </tbody>
</table>
<table class="restore">
    <tbody>
    <tr><td height="40" colspan="7"></td></tr>
    <tr>
        <td></td>
        <td bgcolor="#dddddd"><img src="${path_images}$/restore.gif" alt="restore icon" /></td>
        <td colspan="4" bgcolor="#dddddd"><b>Restore to client</b></td>
        <td></td>
    </tr>
    <tr>
        <td></td>
        <td colspan="5" class="border">
            <table width="100%" border="0" cellpadding="0" cellspacing="0">
            <tr>
                <td valign="bottom">
                    Restore selected objects to:<br />
                    <input type="text"
                        name="target"
                        value="${path_temp}$"
                        style="width: 250px;" />
                </td><td valign="bottom">
                    <input type="checkbox"
                        name="subfolder"
                        value="1" /> Create subfolder with timestamp below<br />
                    <input type="checkbox"
                        name="replace"
                        value="1" /> Replace existing destinations
                </td><td align="right" valign="bottom">
                    <input type="submit"
                        name="restore"
                        value="Restore"
                        onclick="return prompt()" />
                </td>
            </tr>
            </table>
        </td>
        <td></td>
    </tr>
    </tbody>
</table>
<table class="download">
    <tbody>
    <tr><td height="20" colspan="8"></td></tr>
    <tr>
        <td></td>
        <td bgcolor="#dddddd"><img src="${path_images}$/load.gif" alt="load icon"/></td>
        <td colspan="4" bgcolor="#dddddd"><b>Download</b></td>
        <td></td>
    </tr>
    <tr>
        <td></td>
        <td colspan="5" class="border">
            <table width="100%" border="0" cellpadding="0" cellspacing="0">
            <tr>
                <td>Download selected objects as compressed TAR archive.</td>
                <td align="right">
                    <input type="submit" name="download" value="Download" />
                </td>
            </tr>
            </table>
        </td>
        <td></td>
    </tr>
    </tbody>
${:elif not message['error']:}$
    <tbody>
    <tr>
        <td></td>
        <td><img src="${path_images}$/empty.gif" alt="empty directory"/></td>
        <td colspan="4">Directory '${dir}$' is empty</td>
        <td></td>
    </tr>
    </tbody>
${:endif}$
</table>
<table class="usage">
${if usage:}$
    <tbody>
    <tr><td height="40" colspan="8"></td></tr>
    <tr>
        <td></td>
        <td bgcolor="#dddddd"><img src="${path_images}$/chart.gif" alt="chart icon" /></td>
        <td colspan="4" bgcolor="#dddddd"><b>Usage</b></td>
        <td></td>
    </tr>
    <tr>
        <td></td>
        <td colspan="5" class="border">
            <table border="0" cellpadding="2" cellspacing="1">
            ${for item in usage:}$
                <tr>
                <td>${item['name']}$</td>
                <td width="80" align="right">${'%.1f %s' % (item['size'], item['unit'])}$</td>
                <td width="50" align="right">${item['percentage']}$ %</td>
                <td width="300"
                    ><img src="${path_images}$/pix.gif"
                        height="10"
                        width="${emit(item['percentage']*3+1)}$"
                        class="chart" 
                        alt="percentage usage"/></td>
                </tr>
            ${:endfor}$
            </table>
        </td>
        <td></td>
    </tr>
    </tbody>
${:endif}$

</table>
</form>

<div id="footer">
<a href="http://www.joonis.de" target="_blank"><img
    src="http://www.joonis.de/common/images/joonis_button.gif"
    title="joonis new media" alt="joonis footer"/></a>
<a href="http://www.joonis.de/boxbackup-explorer"
    target="_blank">Box Backup Explorer 0.2.3</a>
</div>
</body>
</html>
'''
    
    def __init__(self):
        self.template = Templite(self.template)
        self.message = {'info': [], 'error': []}
        
    def __sudo(self, *args):
        '''Execute a method of class SudoAccess via sudo'''
        proc = subprocess.Popen(
                [path_sudo, script_path] + list(args),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                )
        out, err = proc.communicate()
        retcode = proc.returncode
        if retcode:
            self.message['error'].append(
                "Command '%s' failed with exit code %i: %s" % (args[0], retcode, err))
            return
        return out.strip()
    
    def main(self):
        # Some security checks
        remote_user = os.environ.get('REMOTE_USER')
        remote_addr = os.environ.get('REMOTE_ADDR')
        if script_user != os.geteuid() \
            or (auth_hosts and remote_addr not in auth_hosts) \
            or (auth_users and remote_user not in auth_users) \
            or not (auth_users or remote_user):
            return '''Status: 403 Forbidden\nContent-Type: text/html; charset=utf-8\n
                <!DOCTYPE HTML PUBLIC "-//IETF//DTD HTML 2.0//EN">
                <html>
                <head><title>403 Forbidden</title></head>
                <body>
                <h1>Forbidden</h1>
                <p>Access denied</p>
                <hr />%s
                </body>
                </html>''' % os.environ.get('SERVER_SIGNATURE', '')
        
        form = cgi.FieldStorage()
        dir = os.path.normpath('///%s' % form.getfirst('dir', '/')) 
        now = datetime.datetime.now()
        info = self.message['info']
        error = self.message['error']
        
        if None in auth_users:
            info.append('<b>Warning:</b> Anonymous users not blocked!')
        
        # Process extraction
        extracted = {}
        restore = form.has_key('restore')
        download = form.has_key('download')
        if restore or download:
            source = form.getlist('source')
            if not source:
                info.append('Nothing to do')
            else:
                # Prepare target folder
                if download:
                    target = path_temp
                else:
                    target = form.getfirst('target', path_temp)
                target = os.path.normpath(target)
                if not target.startswith('/'):
                    error.append('Target directory must be an absolute path')
                else:
                    if download or form.has_key('subfolder'):
                        target = os.path.join(target, now.strftime('bbackup_%Y-%m-%d_%H.%M.%S'))
                    if not os.path.isdir(target):
                        self.__sudo('makedir', target)
                        if not error:
                            info.append("Created directory '%s'" % target)
                # Extract objects
                if not error:
                    src_type = ('Directory', 'File')
                    for src in source:
                        status = 0
                        isfile, deleted, isold, object_id, name = src.split('|', 4)
                        dst_path = os.path.join(target, name)
                        if os.path.exists(dst_path):
                            if form.has_key('replace'):
                                result = self.__sudo('rename', dst_path)
                                if result:
                                    info.append("Renamed destination '%s' to '%s'" % (dst_path, result))
                            else:
                                error.append("Destination '%s' already exists, extraction aborted" % dst_path)
                                status = -1
                        if not status:
                            result = self.__sudo('extract', isfile, deleted, dir, object_id, dst_path)
                            if result.count('fetched sucessfully') or result.count('Restore complete'):
                                info.append("%s '%s' successfully extracted to '%s'" % (src_type[int(isfile)], name, target))
                                status = 1
                            else:
                                error.append(result)
                                status = -1
                        if restore:
                            extracted[object_id] = status
                            if int(isold):
                                extracted[md5.md5(name).hexdigest()] = status
                # Create tar archive
                if download and not error:
                    tar_path = self.__sudo('pack', target)
                    if not error:
                        retval = [
                            'Content-Type: Content-Type: application/x-gzip',
                            'Content-Length: %i' % os.path.getsize(tar_path),
                            'Content-Disposition: Attachment; Filename=%s' % os.path.split(tar_path)[1],
                            '']
                        tar = open(tar_path, 'rb')
                        retval.append(tar.read())
                        tar.close()
                    if tar_path and os.path.exists(tar_path):
                        os.remove(tar_path)
                    self.__sudo('removedir', target)
                    if not error:
                        return '\n'.join(retval)
        
        # Get content of remote dir
        content = []
        data = self.__sudo('list', dir)
        if data:
            if data.find('not found on store') > -1:
                error.append(data)
            else:
                content = {}
                rows = data.splitlines()
                for row in rows:
                    cols = row.split(None, 4)
                    modified = [int(v) for v in re.split('[-T:]', cols[2])]
                    modified = datetime.datetime(*modified)
                    item = {
                        'id': cols[0],
                        'name': cols[4],
                        'modified': modified,
                        'size': int(cols[3]) * blocksize,
                        'file': ('f' in cols[1]),
                        'directory': ('d' in cols[1]),
                        'deleted': ('X' in cols[1]),
                        'old': ('o' in cols[1]),
                        'remove': ('R' in cols[1]),
                        'attributes': ('a' in cols[1]),
                        'md5': md5.md5(cols[4]).hexdigest(),
                        'new': (now - modified).days == 0,
                        }
                    # Group objects by name
                    if not content.has_key(item['name']):
                        content[item['name']] = []
                    # We need this to sort the result afterwards
                    content[item['name']].append([
                        item['file'],
                        item['name'].lower(),
                        item['modified'],
                        item,
                        ])
                # Sort
                content = content.values()
                content.sort()
                for item in content:
                    item.reverse()
                    # Remove redundant fields
                    for i in range(len(item)):
                        item[i] = item[i][3]
        
        # Get account usage
        usage = []
        if dir == '/':
            data = self.__sudo('usage')
            if data:
                rows = data.splitlines()
                for row in rows:
                    row = row.replace('*', '').replace('|', '').replace(',', '')
                    cols = row.split()
                    usage.append({
                        'name': ' '.join(cols[-len(cols):-5]),
                        'blocks': int(cols[-5]),
                        'size': float(cols[-3]),
                        'unit': cols[-2],
                        'percentage': int(cols[-1].replace('%', '')),
                        })
        
        return self.template.render({
            'request_uri': os.environ['REQUEST_URI'],
            'script_name': os.environ['SCRIPT_NAME'],
            'path_images': path_images,
            'path_temp': path_temp,
            'dir': dir,
            'message': self.message,
            'content': content,
            'usage': usage,
            'extracted': extracted,
            })


class SudoAccess(object):
    """These methods are executed with root privileges"""
    
    def __init__(self):
        if script_user != int(os.environ.get('SUDO_UID', -1)):
            raise Exception('Executing user does not match script owner')
    
    def __bbquery(self, *args):
        '''Send a query to storage server'''
        return subprocess.call([path_bbquery, '-q'] + list(args) + ['quit'])
    
    def _check_dir(self, dir):
        if not dir.startswith(path_temp):
            raise Exception('Path (%s) does not match temp path (%s)!' % (dir, path_temp))
    
    def list(self, dir):
        return self.__bbquery('list -dots "%s"' % dir)
    
    def usage(self):
        return self.__bbquery('usage')
    
    def extract(self, isfile, deleted, dir, id, dst):
        if int(isfile):
            method = 'get'
        else:
            method = 'restore'
            if int(deleted):
                method += ' -d'
        return self.__bbquery('cd -d "%s"' % dir, '%s -i %s "%s"' % (method, id, dst))
    
    def makedir(self, dir):
        os.makedirs(dir)
        return 0
    
    def removedir(self, dir):
        self._check_dir(dir)
        for root, dirs, files in os.walk(dir, topdown=False):
            for name in files:
                os.remove(os.path.join(root, name))
            for name in dirs:
                os.rmdir(os.path.join(root, name))
        os.rmdir(dir)
        return 0
    
    def rename(self, path):
        num = 0
        while True:
            num += 1
            dst = '%s.bbackup.%i' % (path, num)
            if not os.path.exists(dst):
                break
        os.rename(path, dst)
        print dst
        return 0
    
    def pack(self, dir):
        self._check_dir(dir)
        file = dir + '.tar.gz'
        tar = tarfile.open(file, 'w:gz')
        print file
        tar.add(dir, os.path.split(dir)[1])
        tar.close()
        os.chown(file, script_user, script_user)
        return 0
        


if __name__ == '__main__':
        
    if len(sys.argv) == 1:
        # CGI access
        cgitb.enable()
        app = CgiAccess()
        sys.stdout.write(app.main())
    else:
        # SUDO access
        try:
            app = SudoAccess()
            retcode = app.__getattribute__(sys.argv[1])(*sys.argv[2:])
        except Exception, err:
            retcode = 1
            sys.stderr.write('%s\n' % str(err))
        
        sys.exit(retcode)
