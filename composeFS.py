#!/usr/bin/env python

from fuse import Fuse, Stat
import fuse
import stat
fuse.fuse_python_api=(0,2)
import sys
import os
import re
import io
from contextlib import closing, contextmanager
from unicodedata import name as uniname
from functools import update_wrapper

@contextmanager
def redirstdout(fd):
    hold=sys.stdout
    sys.stdout=fd
    try:
        yield
    finally:
        sys.stdout=hold

# def DBGmsg(msg):
#    ComposeFuse.DBG.write(msg)
#    ComposeFuse.DBG.flush()
def DBGmsg(msg):
    pass

# def debugfunc(func):
#     def blah(*args, **kwargs):
#         DBGmsg("Entering %s(%s :: %s)\n"%(func.func_name,
#                                                          repr(args),
#                                                          repr(kwargs)))
#         rv=func(*args, **kwargs)
#         DBGmsg("Leaving %s (%s)\n"%(func.func_name, repr(rv)[:100]))
#         return rv
#     return update_wrapper(blah,func)

# Dummy decorator.
def debugfunc(func):
    return func

def flattendict(dct, prefixes=None, rv=None):
    """Take nested dict and return flattened version"""
    if rv is None:
        rv={}
    if prefixes is None:
        prefixes=[]
    for (k, v) in dct.iteritems():
        if isinstance(v, dict):
            flattendict(v, prefixes+[k], rv)
        else:
            rv[tuple(prefixes+[k])]=v
    return rv

def flatascompose(dct, stream=sys.stdout):
    # dct comes in as a flattened dictionary of
    # {(tuple of keys):(value, lineno, preceding-comments)}.  Want to output
    # it in order of lineno.
    try:
        #  XXX Gonna have to change for py3
        allentries=sorted(dct.items(), cmp=lambda a,b : cmp(a[1][1],
                                                            b[1][1]))
        for ent in allentries:
            try:
                (key, data)=ent
                (val, lineno, comments, inline)=data
                stream.write(unicode(comments))
                stream.write(u' '.join(u'<{0}>'.format(unicode(_)) for _ in key))
                stream.write(u'\t:\t"{}"'.format(val))
                if inline:
                    if len(val)==1:
                        stream.write(u"\tU{:04X}\t## {}\n".format(ord(val),
                                                                  inline))
                    else: 
                        stream.write(u'\t## {}\n'.format(inline))
                elif len(val)==1:
                    try:
                        stream.write(u'\tU{:04X}\t# {}\n'.format(ord(val), 
                                                                 uniname(val)))
                    except ValueError:
                        stream.write(u'\tU{:04X}\t# {}\n'.format(ord(val), "????"))
                else:
                    stream.write(u"\n")
            except (Exception,Error) as E:
                pass
    except (Exception,Error) as E:
        DBGmsg(u"AAH! "+str(E)+u"\n")
    finally:
        DBGmsg(u"\nAnd done now.\n")

# Copied in from treeprint.py and tweaked/improved
def readfile(*files):
    listing={}
    linecount=0
    comments=""

    for filename in files:
        with closing(open(filename,"r")) as fd:
            for line in fd:
                linecount+=1
                line=line.decode('utf-8')
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
                    comments+=line
                    continue
                m=re.match(ur'[^"]*"(.+?)"',line)
                if not m:
                    # shouldn't happen, but just in case
                    val=u'???'
                    print("couldn't make sense of line: "+line)
                else:
                    val=unicode(m.group(1))
                # Can't otherwise distinguish between auto-inlines and custom...
                m=re.search(ur'## *(.*)$', line)
                if m:
                    inline=unicode(m.group(1))
                else:
                    inline=u""
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
                    cur[name[-1]]=(val, linecount,
                                   comments, inline)
                    comments=""
                    inline=""
                else:
                    # fail.  Prefix conflict.  Let's ignore it.
                    pass
    #print(repr(listing))
    if comments:                # Ending comments
        listing[" ENDING "]=(u"", lineno, comments)
    return listing

class ComposeFuse(Fuse):
    # DBG=open("/home/mark/xcompose/TREEDUMP","w")

    fieldsep='-'
    def __init__(self, *args, **kwargs):
        Fuse.__init__(self, *args, **kwargs)

    @debugfunc
    def fsinit(self):
        infiles=self.infile.split('|')
        self.listing=readfile(*list(os.path.expanduser(_) for _ in infiles))
        print(repr(self.listing))
        self.encoding=getattr(self, 'encoding', 'utf8')
        self.errors=getattr(self, 'errors', 'strict')
        self.outfile=getattr(self, 'outfile', None)
        if self.outfile is not None:
            self.outfile=os.path.expanduser(self.outfile)
            try:
                if not os.path.isabs(self.outfile[0]):
                    self.outfile = os.path.abspath(self.outfile)
            except IndexError:
                # If it's the null string--if they just say outfile=
                self.outfile = os.path.abspath("COMPOSEDUMP")
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
        if self.outfile:
            try:
                with closing(io.open(self.outfile,"w",encoding='utf-8',newline=u"\n")) as fd:
                    flatascompose(flattendict(self.listing), stream=fd)
            except (Exception, Error) as E:
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
        suffix=None
        # The names are very limited, and this only happens for leaves.
        try:
            (realpath,suffix)=path.rsplit(self.fieldsep,1)
            path=realpath
        except ValueError:
            pass
        pathelts=self.getParts(path)
        elt=self.followpath(pathelts)
        if elt is None:
            return -fuse.ENOENT
        if self.is_directory(None, pathelts):
            st.st_mode=stat.S_IFDIR | 0o755
            st.st_nlink=2
            st.st_ctime=0
            st.st_atime=0
            st.st_mtime=0
        else:
            st.st_mode=stat.S_IFREG | 0o644
            st.st_nlink=1
            st.st_size=len(elt[0].encode(self.encoding))
            st.st_ctime=elt[1]*3600*24
            st.st_atime=st.st_ctime
            st.st_mtime=st.st_ctime
            if suffix=='COMMENTS':
                st.st_size=len(elt[2].encode(self.encoding))
            elif suffix=='INLINE':
                st.st_size=len(elt[3].encode(self.encoding))
            elif suffix:        # not one of the allowed ones.
                return -fuse.ENOENT
        st.st_ino=0
        st.st_def=0
        st.st_uid=0
        st.st_gid=0
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
            if not isinstance(elt[en], dict):
                if elt[en][2]:  # Has comments.
                    yield fuse.Direntry(en+self.fieldsep+"COMMENTS")
                if elt[en][3]:  # Has inline
                    yield fuse.Direntry(en+self.fieldsep+"INLINE")
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
        # Unlinking an entry removes its comments as well, etc.
        suffix=None
        try:
            (realpath,suffix)=path.rsplit(self.fieldsep,1)
            path=realpath
        except ValueError:
            pass
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
        suffix=None
        try:
            (realpath,suffix)=path.rsplit(self.fieldsep,1)
            path=realpath
        except ValueError:
            pass
        pathelts=self.getParts(path)
        parent=self.followpath(pathelts[:-1])
        item=parent.get(pathelts[-1], '')
        if isinstance(item, dict):
            return -fuse.EISDIR
        # The item is a tuple, can't replace it in pieces.
        newitem=list(item)
        # Val, lineno, comments, inline
        if suffix=="COMMENTS":
            newitem[2]=unicode(buf) # offset?
        elif suffix=="INLINE":
            newitem[3]=unicode(buf)
        elif suffix:
            return -fuse.ENOENT
        else:
            newitem[0]=unicode(buf)
        parent[pathelts[-1]]=tuple(newitem)
        return len(unicode(buf).encode(self.encoding))

    def truncate(self, path, length):
        return 0                # Whatever...

    @debugfunc
    def read(self, path, size, offset):
        suffix=None
        try:
            (realpath,suffix)=path.rsplit(self.fieldsep,1)
            path=realpath
        except ValueError:
            pass
        elt=self.followpath(self.getParts(path))
        if isinstance(elt, dict):
            return -fuse.EISDIR
        if suffix=='COMMENTS':
            return elt[2][offset:offset+size+1].encode(self.encoding)
        elif suffix=='INLINE':
            return elt[3][offset:offset+size+1].encode(self.encoding)
        # Wait, do subscripting or encoding first?
        return elt[0][offset:offset+size+1].encode(self.encoding, self.errors)

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

try:
    server=ComposeFuse(version="%prog "+fuse.__version__,
                       usage='', dash_s_do='setsingle')
    server.path=os.getcwd()
    server.parser.add_option(mountopt="infile")
    server.parser.add_option(mountopt="outfile")
    server.parser.add_option(mountopt="encoding")
    server.parser.add_option(mountopt="errors")
    server.parse(errex=1, values=server)
    server.fsinit()
    server.main()
except AttributeError:           # Catch python -i calls
    pass
