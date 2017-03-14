#!/usr/bin/env python3

import fuse
import stat
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
#         DBGmsg("Entering %s(%s :: %s)\n"%(func.__name__,
#                                                          repr(args),
#                                                          repr(kwargs)))
#         rv=func(*args, **kwargs)
#         DBGmsg("Leaving %s (%s)\n"%(func.__name__, repr(rv)[:100]))
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
    for (k, v) in dct.items():
        if isinstance(v, dict):
            flattendict(v, prefixes+[k], rv)
        else:
            rv[tuple(prefixes+[k])]=v
    return rv

COUNTFILE='.linecount'

def flatascompose(dct, stream=sys.stdout):
    # dct comes in as a flattened dictionary of
    # {(tuple of keys):(value, lineno, preceding-comments)}.  Want to output
    # it in order of lineno.
    try:
        allentries=sorted(dct.items(), key=lambda x: x[1][1])
        for ent in allentries:
            try:
                (key, data)=ent
                (val, lineno, comments, inline)=data
                stream.write(str(comments))
                if key[-1]==COUNTFILE:
                    continue
                # Catch "Ending" special-case
                if not val:
                    continue
                # split keys on commas and flatten:
                # http://stackoverflow.com/questions/952914/making-a-flat-list-out-of-list-of-lists-in-python
                key=[item for sublist in [x.split(",") for x in key] for item in sublist]
                stream.write(u' '.join(u'<{0}>'.format(str(_)) for _ in key))
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
            except (Exception,) as E:
                pass
    except (Exception,) as E:
        DBGmsg(u"AAH! "+str(E)+u"\n")
    finally:
        DBGmsg(u"\nAnd done now.\n")

def compressdict(dct):
    """Take a dict in usual form and *destructively* modify it so as to
    compress nests of one-element dictionaries into keys made of
    comma-separate elements.  Also returns the dictionary; works
    recursively.
    """
    if isinstance(dct, dict):
        for k,v in dct.items():
            if isinstance(v, dict):
                if len(v) == 1:
                    # is there a better way to do this or tell we're done?
                    # This works!?  OK then.
                    currkey=None
                    while isinstance(v, dict) and currkey!=next(iter(v.keys())):
                        currkey=next(iter(v.keys()))
                        dct[k+","+currkey] = v = compressdict(next(iter(v.values())))
                        del dct[k]
                        k=k+","+currkey
                else:
                    dct[k] = compressdict(v)
    return dct

# Copied in from treeprint.py and tweaked/improved
def readfile(*files):
    listing={}
    linecount=0
    comments=""

    for filename in files:
        with closing(open(filename,"r")) as fd:
            for line in fd:
                linecount+=1
                #line=line.decode('utf-8')
                startpos=0
                name=[]
                dupsfound=[]
                while True:
                    m=re.match("\s*<(\w+)>",line[startpos:])
                    if not m:
                        break
                    word=m.group(1)
                    name.append(str(word))
                    startpos+=m.end()
                if startpos<=0:
                    comments+=line
                    continue
                m=re.match(r'[^"]*"(.+?)"',line)
                if not m:
                    # shouldn't happen, but just in case
                    val=u'???'
                    print("couldn't make sense of line: "+line)
                else:
                    val=str(m.group(1))
                # Can't otherwise distinguish between auto-inlines and custom...
                m=re.search(r'## *(.*)$', line)
                if m:
                    inline=str(m.group(1))
                else:
                    inline=u""
                cur=listing
                for elt in name[:-1]:
                    if type(cur)==dict:
                        if not elt in cur:
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
    if comments:                # Ending comments; dummy entry
        listing["ENDING"]=(u"", linecount, comments, "")
    listing[COUNTFILE]=(str(linecount), linecount, "", "")
    return listing

class ComposeFuse(fuse.Operations):
    # DBG=open(os.getenv('HOME')+os.sep+"XCOMPDBG","w")

    fieldsep='-'

    @debugfunc
    def init(self, *args):
        infiles=self.infile.split('|')
        self.listing=readfile(*list(os.path.expanduser(_) for _ in infiles))
        if getattr(self, 'compress', False):
            self.listing=compressdict(self.listing)
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
    def destroy(self, *args, **kwargs):
        if self.outfile:
            with closing(io.open(self.outfile,"w",encoding='utf-8',newline=u"\n")) as fd:
                flatascompose(flattendict(self.listing), stream=fd)

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
    def getattr(self, path, fh=None):
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
            raise fuse.FuseOSError(fuse.ENOENT)
        if self.is_directory(None, pathelts):
            st=dict(st_mode=stat.S_IFDIR | 0o755,
                    st_nlink=2+len(elt),
                    st_ctime=0,
                    st_atime=0,
                    st_mtime=0)
        else:
            # Use ls -l --time-style="+%s"
            st=dict(st_mode=stat.S_IFREG | 0o644,
                    st_nlink=1,
                    st_size=len(elt[0].encode(self.encoding)),
                    st_ctime=elt[1],
                    st_atime=elt[1],
                    st_mtime=elt[1])
            if suffix=='COMMENTS':
                st['st_size']=len(elt[2].encode(self.encoding))
            elif suffix=='INLINE':
                st['st_size']=len(elt[3].encode(self.encoding))
            elif suffix:        # not one of the allowed ones.
                raise fuse.FuseOSError(fuse.ENOENT)
            # Doesn't seem to accomplish much:
            if pathelts[-1]==COUNTFILE:
                st['st_mode'] = stat.S_IFREG | 0o444 # read-only special case
        st['st_ino']=0
        st['st_def']=0
        st['st_uid']=0
        st['st_gid']=0
        return st

    readlink=None

    def readdir(self, path, offset):
        pathelts=self.getParts(path)
        if self.is_root(path):
            elt=self.listing
        else:
            elt=self.followpath(pathelts)
        if elt is None:
            raise fuse.FuseOSError(fuse.ENOENT)
        if not self.is_directory(None, pathelts):
            raise fuse.FuseOSError(fuse.ENOTDIR)
        yield '.'
        yield '..'
        entries=sorted(elt.keys())
        for en in entries:
            if not isinstance(elt[en], dict):
                if elt[en][2]:  # Has comments.
                    yield en+self.fieldsep+"COMMENTS"
                if elt[en][3]:  # Has inline
                    yield en+self.fieldsep+"INLINE"
            yield en
        return

    @debugfunc
    def create(self, path, mode):
        pathelts=self.getParts(path)
        elt=self.followpath(pathelts[:-1])
        if elt is None or not isinstance(elt, dict):
            raise fuse.FuseOSError(fuse.ENOENT)
        if pathelts[-1] in elt:
            raise fuse.FuseOSError(fuse.EEXIST)
        try:
            lc=self.listing[COUNTFILE][1] + 1
            self.listing[COUNTFILE]=(str(lc), lc, "", "")
        except KeyError:
            lc=10000 # why _not_ 10,000?
        elt[pathelts[-1]]=("", lc, "", "")
        return 0

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
            raise fuse.FuseOSError(fuse.ENOENT)
        if pathelts[-1] in elt:
            raise fuse.FuseOSError(fuse.EEXIST)
        elt[pathelts[-1]]={}
        return

    @debugfunc
    def write(self, path, buf, offset, fh=None):
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
            raise fuse.FuseOSError(fuse.EISDIR)
        # The item is a tuple, can't replace it in pieces.
        newitem=list(item)
        # Val, lineno, comments, inline
        if suffix=="COMMENTS":
            newitem[2]=buf.decode('utf-8') # offset? Catch exceptions?
        elif suffix=="INLINE":
            newitem[3]=buf.decode('utf-8')
        elif suffix:
            raise fuse.FuseOSError(fuse.ENOENT)
        else:
            newitem[0]=buf.decode('utf-8')
        parent[pathelts[-1]]=tuple(newitem)
        return len(str(buf).encode(self.encoding))

    def truncate(self, path, length):
        return 0                # Whatever...

    @debugfunc
    def read(self, path, size, offset, fh=None):
        suffix=None
        try:
            (realpath,suffix)=path.rsplit(self.fieldsep,1)
            path=realpath
        except ValueError:
            pass
        elt=self.followpath(self.getParts(path))
        if isinstance(elt, dict):
            raise fuse.FuseOSError(fuse.EISDIR)
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

    symlink=None

    link=None

    @debugfunc
    def chmod(self, *args):
        pass

if __name__ == '__main__':
    server=ComposeFuse()
    server.path=os.getcwd()

    # simple parsing, not bothering with true option parser.
    # infile, outfile, [encoding], [errors]
    if sys.argv[1].startswith("-o"):
        opts=sys.argv.pop(1)
        if opts=='-o':
            opts=sys.argv.pop(1)
        else:
            opts=opts[2:]
        for opt in opts.split(","):
            try:
                nam, val = opt.split('=',2)
            except ValueError:
                nam, val = opt, True
            if not val:
                val=True        # opt=
            # If you abuse this to overwrite stuff the class needs,
            # you deserve whatever you get.
            setattr(server, nam, val)
    mntpt=sys.argv[1]


    if not hasattr(server, 'infile') or not server.infile:
        print("Need infile.")
        exit(1)
    fu=fuse.FUSE(server, mntpt, foreground=hasattr(server,'foreground'),
                 nothreads=True)
