#!/usr/bin/env python

from fuse import Fuse, Stat
import fuse
import stat
fuse.fuse_python_api=(0,2)
import sys
import os
import re
from contextlib import closing

# def debugfunc(func):
#     def blah(*args, **kwargs):
#         ComposeFuse.DBG.write("Entering %s(%s :: %s)\n"%(func.func_name,
#                                                          repr(args),
#                                                          repr(kwargs)))
#         rv=func(*args, **kwargs)
#         ComposeFuse.DBG.write("Leaving %s (%s)\n"%(func.func_name, repr(rv)[:100]))
#         ComposeFuse.DBG.flush()
#         return rv
#     return blah

def debugfunc(func):
    return func

# Copied in from treeprint.py and tweaked/improved
def readfile(filename):
    listing={}

    with closing(open(filename,"r")) as fd:
        for line in fd:
            line=line.decode('utf-8')
            # print "((%s))"%line
            startpos=0
            name=[]
            dupsfound=[]
            while True:
                m=re.match("\s*<(\w+)>",line[startpos:])
                if not m:
                    break
                word=m.group(1)
                name.append(str(word)) # The keys are ordinary strings, not unicode
                startpos+=m.end()
            if startpos<=0:
                continue
            m=re.match(r'[^"]*"(.+?)"',line)
            if not m:
                # shouldn't happen, but just in case
                val='???'
                print "couldn't make sense of line: "+line
            else:
                val=m.group(1)
            cur=listing
            for elt in name[:-1]:
                if type(cur)==dict:
                    if not cur.has_key(elt):
                        cur[elt]={}
                    cur=cur[elt]        # This will fail for prefix conflicts
                else:
                    break           # prefix conflict
            # Presumably by now we're at the end, pointing to an empty dict.
            if type(cur)==dict:
                cur[name[-1]]=val
            else:
                # fail.  Prefix conflict.  Let's ignore it.
                pass
    print(repr(listing))
    return listing

class ComposeFuse(Fuse):
    
    def __init__(self, *args, **kwargs):
        Fuse.__init__(self, *args, **kwargs)

    @debugfunc
    def fsinit(self):
        self.listing=readfile(self.infile)
        self.encoding=getattr(self, 'encoding', 'utf8')
        self.errors=getattr(self, 'errors', 'strict')
        self.outfile=getattr(self, 'outfile', 'XCOMPOSE-OUT.compose')
        import codecs
        try:
            codecs.getencoder(self.encoding)
        except LookupError:
            self.encoding='utf8'
        if self.errors not in ['strict', 'ignore', 'replace',
                               'xmlcharrefreplace']:
            self.errors='strict'

    @debugfunc
    def fsdestroy(self):
        # Output Compose file from fs!
        pass

    @staticmethod
    def getParts(path):
        """
        Return the slash-separated parts of a given path as a list
        """
        if path == os.sep:
            return [os.sep]
        else:
            parts=path.split(os.sep)
            if parts[0]=='':
                parts.pop(0)
            return parts

    @debugfunc
    def followpath(self, pathelts):
        rv=self.listing
        if self.is_root(None, pathelts):
            return self.listing
        try:
            for elt in pathelts:
                rv=rv[elt]
        except (KeyError, TypeError):
            rv=None
        return rv

    @debugfunc
    def is_root(self, path=None, pathelts=None):
        if pathelts is None:
            pathelts=self.getParts(path)
        return (path==os.sep or len(pathelts)==0 or
                pathelts == ['/'])

    @debugfunc
    def is_directory(self, path=None, pathelts=None):
        if not pathelts:
            pathelts=self.getParts(path)
        rv=self.followpath(pathelts)
        return isinstance(rv, dict)

    @debugfunc
    def getattr(self, path):
        st=Stat()
        pathelts=self.getParts(path)
        elt=self.followpath(pathelts)
        if elt is None:
            return -fuse.ENOENT
        if self.is_directory(None, pathelts):
            st.st_mode=stat.S_IFDIR | 0755
            st.st_nlink=2
        else:
            st.st_mode=stat.S_IFREG | 0644
            st.st_nlink=1
            st.st_size=len(elt.encode(self.encoding, self.errors))
        st.st_ino=0
        st.st_def=0
        st.st_uid=0
        st.st_gid=0
        st.st_atime=0
        st.st_mtime=0
        st.st_ctime=0
        return st

    @debugfunc
    def readlink(self, path):
        return -fuse.ENOENT

    def readdir(self, path, offset):
        pathelts=self.getParts(path)
        if self.is_root(path):
            elt=self.listing
        else:
            elt=self.followpath(pathelts)
        if elt is None:
            yield -fuse.ENOENT
            return
        if not self.is_directory(None, pathelts):
            yield -fuse.ENOTDIR
            return
        yield fuse.Direntry('.')
        yield fuse.Direntry('..')
        entries=sorted(elt.keys())
        for en in entries:
            yield fuse.Direntry(en)
        return

    @debugfunc
    def mknod(self, path, mode, dev):
        if mode & stat.S_IFREG and dev==0:
            pathelts=self.getParts(path)
            parent=self.followpath(pathelts[:-1])
            if parent is None:
                return -fuse.ENOENT
            if not isinstance(parent, dict):
                return -fuse.EEXIST
            if pathelts[-1] in parent:
                return -fuse.EEXIST
            parent[pathelts[-1]]=''
        else:
            return -fuse.ENOSYS

    @debugfunc
    def unlink(self, path):
        pathelts=self.getParts(path)
        parent=self.followpath(pathelts[:-1])
        del parent[pathelts[-1]]
    rmdir = unlink              # ?

    @debugfunc
    def mkdir(self, path, mode):
        pathelts=self.getParts(path)
        elt=self.followpath(pathelts[:-1])
        if elt is None or not isinstance(elt, dict):
            return -fuse.ENOENT
        if pathelts[-1] in elt:
            return -fuse.EEXIST
        elt[pathelts[-1]]={}
        return

    @debugfunc
    def write(self, path, buf, offset):
        pathelts=self.getParts(path)
        parent=self.followpath(pathelts[:-1])
        item=parent.get(pathelts[-1], '')
        if isinstance(item, dict):
            return -fuse.EISDIR
        # Ah, screw offsets.
        parent[pathelts[-1]]=buf
        return len(buf)

    def truncate(self, path, length):
        return 0                # Whatever...

    @debugfunc
    def read(self, path, size, offset):
        elt=self.followpath(self.getParts(path))
        if isinstance(elt, dict):
            return -fuse.EISDIR
        # Wait, do subscripting or encoding first?
        return elt[offset:offset+size+1].encode(self.encoding, self.errors)
 
    @debugfunc
    def release(self, path, flags):
        return 0

    @debugfunc
    def open(self, path, flags):
        return 0

    @debugfunc
    def symlink(self, *args):
        return -fuse.ENOSYS

    @debugfunc
    def link(self, *args):
        return -fuse.ENOSYS

    @debugfunc
    def chmod(self, *args):
        pass

server=ComposeFuse(version="%prog "+fuse.__version__,
                   usage='', dash_s_do='setsingle')
server.path=os.getenv('PWD')
server.parser.add_option(mountopt="infile")
server.parser.add_option(mountopt="outfile")
server.parser.add_option(mountopt="encoding")
server.parser.add_option(mountopt="errors")
server.parse(errex=1, values=server)
server.fsinit()
server.main()
