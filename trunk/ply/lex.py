# -----------------------------------------------------------------------------
# ply: lex.py
#
# Author: David M. Beazley (dave@dabeaz.com)
#
# Copyright (C) 2001-2009, David M. Beazley
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this library; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA
#
# See the file COPYING for a complete copy of the LGPL.
# -----------------------------------------------------------------------------

__version__    = "3.0"
__tabversion__ = "3.0"       # Version of table file used

import re, sys, types, copy, os

# This tuple contains known string types
try:
    # Python 2.6
    StringTypes = (types.StringType, types.UnicodeType)
except AttributeError:
    # Python 3.0
    StringTypes = (str, bytes)

# Extract the code attribute of a function. Different implementations
# are for Python 2/3 compatibility.

if sys.version_info[0] < 3:
    def func_code(f):
        return f.func_code
else:
    def func_code(f):
        return f.__code__

# This regular expression is used to match valid token names
_is_identifier = re.compile(r'^[a-zA-Z0-9_]+$')

# Exception thrown when invalid token encountered and no default error
# handler is defined.

class LexError(Exception):
    def __init__(self,message,s):
         self.args = (message,)
         self.text = s

# Token class.  This class is used to represent the tokens produced.
class LexToken(object):
    def __str__(self):
        return "LexToken(%s,%r,%d,%d)" % (self.type,self.value,self.lineno,self.lexpos)
    def __repr__(self):
        return str(self)

# -----------------------------------------------------------------------------
# Lexer class
#
# This class encapsulates all of the methods and data associated with a lexer.
#
#    input()          -  Store a new string in the lexer
#    token()          -  Get the next token
# -----------------------------------------------------------------------------

class Lexer:
    def __init__(self):
        self.lexre = None             # Master regular expression. This is a list of
                                      # tuples (re,findex) where re is a compiled
                                      # regular expression and findex is a list
                                      # mapping regex group numbers to rules
        self.lexretext = None         # Current regular expression strings
        self.lexstatere = {}          # Dictionary mapping lexer states to master regexs
        self.lexstateretext = {}      # Dictionary mapping lexer states to regex strings
        self.lexstaterenames = {}     # Dictionary mapping lexer states to symbol names
        self.lexstate = "INITIAL"     # Current lexer state
        self.lexstatestack = []       # Stack of lexer states
        self.lexstateinfo = None      # State information
        self.lexstateignore = {}      # Dictionary of ignored characters for each state
        self.lexstateerrorf = {}      # Dictionary of error functions for each state
        self.lexreflags = 0           # Optional re compile flags
        self.lexdata = None           # Actual input data (as a string)
        self.lexpos = 0               # Current position in input text
        self.lexlen = 0               # Length of the input text
        self.lexerrorf = None         # Error rule (if any)
        self.lextokens = None         # List of valid tokens
        self.lexignore = ""           # Ignored characters
        self.lexliterals = ""         # Literal characters that can be passed through
        self.lexmodule = None         # Module
        self.lineno = 1               # Current line number
        self.lexdebug = 0             # Debugging mode
        self.lexoptimize = 0          # Optimized mode

    def clone(self,object=None):
        c = copy.copy(self)

        # If the object parameter has been supplied, it means we are attaching the
        # lexer to a new object.  In this case, we have to rebind all methods in
        # the lexstatere and lexstateerrorf tables.

        if object:
            newtab = { }
            for key, ritem in self.lexstatere.items():
                newre = []
                for cre, findex in ritem:
                     newfindex = []
                     for f in findex:
                         if not f or not f[0]:
                             newfindex.append(f)
                             continue
                         newfindex.append((getattr(object,f[0].__name__),f[1]))
                newre.append((cre,newfindex))
                newtab[key] = newre
            c.lexstatere = newtab
            c.lexstateerrorf = { }
            for key, ef in self.lexstateerrorf.items():
                c.lexstateerrorf[key] = getattr(object,ef.__name__)
            c.lexmodule = object
        return c

    # ------------------------------------------------------------
    # writetab() - Write lexer information to a table file
    # ------------------------------------------------------------
    def writetab(self,tabfile,outputdir=""):
        if isinstance(tabfile,types.ModuleType):
            return
        basetabfilename = tabfile.split(".")[-1]
        filename = os.path.join(outputdir,basetabfilename)+".py"
        tf = open(filename,"w")
        tf.write("# %s.py. This file automatically created by PLY (version %s). Don't edit!\n" % (tabfile,__version__))
        tf.write("_lextokens    = %s\n" % repr(self.lextokens))
        tf.write("_lexreflags   = %s\n" % repr(self.lexreflags))
        tf.write("_lexliterals  = %s\n" % repr(self.lexliterals))
        tf.write("_lexstateinfo = %s\n" % repr(self.lexstateinfo))

        tabre = { }
        # Collect all functions in the initial state
        initial = self.lexstatere["INITIAL"]
        initialfuncs = []
        for part in initial:
            for f in part[1]:
                if f and f[0]:
                    initialfuncs.append(f)

        for key, lre in self.lexstatere.items():
             titem = []
             for i in range(len(lre)):
                  titem.append((self.lexstateretext[key][i],_funcs_to_names(lre[i][1],self.lexstaterenames[key][i])))
             tabre[key] = titem

        tf.write("_lexstatere   = %s\n" % repr(tabre))
        tf.write("_lexstateignore = %s\n" % repr(self.lexstateignore))

        taberr = { }
        for key, ef in self.lexstateerrorf.items():
             if ef:
                  taberr[key] = ef.__name__
             else:
                  taberr[key] = None
        tf.write("_lexstateerrorf = %s\n" % repr(taberr))
        tf.close()

    # ------------------------------------------------------------
    # readtab() - Read lexer information from a tab file
    # ------------------------------------------------------------
    def readtab(self,tabfile,fdict):
        if isinstance(tabfile,types.ModuleType):
            lextab = tabfile
        else:
            if sys.version_info[0] < 3:
                exec("import %s as lextab" % tabfile)
            else:
                env = { }
                exec("import %s as lextab" % tabfile, env,env)
                lextab = env['lextab']

        self.lextokens      = lextab._lextokens
        self.lexreflags     = lextab._lexreflags
        self.lexliterals    = lextab._lexliterals
        self.lexstateinfo   = lextab._lexstateinfo
        self.lexstateignore = lextab._lexstateignore
        self.lexstatere     = { }
        self.lexstateretext = { }
        for key,lre in lextab._lexstatere.items():
             titem = []
             txtitem = []
             for i in range(len(lre)):
                  titem.append((re.compile(lre[i][0],lextab._lexreflags),_names_to_funcs(lre[i][1],fdict)))
                  txtitem.append(lre[i][0])
             self.lexstatere[key] = titem
             self.lexstateretext[key] = txtitem
        self.lexstateerrorf = { }
        for key,ef in lextab._lexstateerrorf.items():
             self.lexstateerrorf[key] = fdict[ef]
        self.begin('INITIAL')

    # ------------------------------------------------------------
    # input() - Push a new string into the lexer
    # ------------------------------------------------------------
    def input(self,s):
        # Pull off the first character to see if s looks like a string
        c = s[:1]
        if not isinstance(c,StringTypes):
            raise ValueError("Expected a string")
        self.lexdata = s
        self.lexpos = 0
        self.lexlen = len(s)

    # ------------------------------------------------------------
    # begin() - Changes the lexing state
    # ------------------------------------------------------------
    def begin(self,state):
        if not state in self.lexstatere:
            raise ValueError("Undefined state")
        self.lexre = self.lexstatere[state]
        self.lexretext = self.lexstateretext[state]
        self.lexignore = self.lexstateignore.get(state,"")
        self.lexerrorf = self.lexstateerrorf.get(state,None)
        self.lexstate = state

    # ------------------------------------------------------------
    # push_state() - Changes the lexing state and saves old on stack
    # ------------------------------------------------------------
    def push_state(self,state):
        self.lexstatestack.append(self.lexstate)
        self.begin(state)

    # ------------------------------------------------------------
    # pop_state() - Restores the previous state
    # ------------------------------------------------------------
    def pop_state(self):
        self.begin(self.lexstatestack.pop())

    # ------------------------------------------------------------
    # current_state() - Returns the current lexing state
    # ------------------------------------------------------------
    def current_state(self):
        return self.lexstate

    # ------------------------------------------------------------
    # skip() - Skip ahead n characters
    # ------------------------------------------------------------
    def skip(self,n):
        self.lexpos += n

    # ------------------------------------------------------------
    # token() - Return the next token from the Lexer
    #
    # Note: This function has been carefully implemented to be as fast
    # as possible.  Don't make changes unless you really know what
    # you are doing
    # ------------------------------------------------------------
    def token(self):
        # Make local copies of frequently referenced attributes
        lexpos    = self.lexpos
        lexlen    = self.lexlen
        lexignore = self.lexignore
        lexdata   = self.lexdata

        while lexpos < lexlen:
            # This code provides some short-circuit code for whitespace, tabs, and other ignored characters
            if lexdata[lexpos] in lexignore:
                lexpos += 1
                continue

            # Look for a regular expression match
            for lexre,lexindexfunc in self.lexre:
                m = lexre.match(lexdata,lexpos)
                if not m: continue

                # Create a token for return
                tok = LexToken()
                tok.value = m.group()
                tok.lineno = self.lineno
                tok.lexpos = lexpos

                i = m.lastindex
                func,tok.type = lexindexfunc[i]

                if not func:
                   # If no token type was set, it's an ignored token
                   if tok.type:
                      self.lexpos = m.end()
                      return tok
                   else:
                      lexpos = m.end()
                      break

                lexpos = m.end()

                # if func not callable, it means it's an ignored token
                if not hasattr(func,"__call__"):
                   break

                # If token is processed by a function, call it

                tok.lexer = self      # Set additional attributes useful in token rules
                self.lexmatch = m
                self.lexpos = lexpos

                newtok = func(tok)

                # Every function must return a token, if nothing, we just move to next token
                if not newtok:
                    lexpos    = self.lexpos         # This is here in case user has updated lexpos.
                    lexignore = self.lexignore      # This is here in case there was a state change
                    break

                # Verify type of the token.  If not in the token map, raise an error
                if not self.lexoptimize:
                    if not newtok.type in self.lextokens:
                        raise LexError("%s:%d: Rule '%s' returned an unknown token type '%s'" % (
                            func_code(func).co_filename, func_code(func).co_firstlineno,
                            func.__name__, newtok.type),lexdata[lexpos:])

                return newtok
            else:
                # No match, see if in literals
                if lexdata[lexpos] in self.lexliterals:
                    tok = LexToken()
                    tok.value = lexdata[lexpos]
                    tok.lineno = self.lineno
                    tok.type = tok.value
                    tok.lexpos = lexpos
                    self.lexpos = lexpos + 1
                    return tok

                # No match. Call t_error() if defined.
                if self.lexerrorf:
                    tok = LexToken()
                    tok.value = self.lexdata[lexpos:]
                    tok.lineno = self.lineno
                    tok.type = "error"
                    tok.lexer = self
                    tok.lexpos = lexpos
                    self.lexpos = lexpos
                    newtok = self.lexerrorf(tok)
                    if lexpos == self.lexpos:
                        # Error method didn't change text position at all. This is an error.
                        raise LexError("Scanning error. Illegal character '%s'" % (lexdata[lexpos]), lexdata[lexpos:])
                    lexpos = self.lexpos
                    if not newtok: continue
                    return newtok

                self.lexpos = lexpos
                raise LexError("Illegal character '%s' at index %d" % (lexdata[lexpos],lexpos), lexdata[lexpos:])

        self.lexpos = lexpos + 1
        if self.lexdata is None:
             raise RuntimeError("No input string given with input()")
        return None

    # Iterator interface
    def __iter__(self):
        return self

    def next(self):
        t = self.token()
        if t is None:
            raise StopIteration
        return t

    __next__ = next


# -----------------------------------------------------------------------------
# _validate_file()
#
# This checks to see if there are duplicated t_rulename() functions or strings
# in the parser input file.  This is done using a simple regular expression
# match on each line in the given file.  If the file can't be located or opened,
# a true result is returned by default.
# -----------------------------------------------------------------------------

def _validate_file(filename):
    import os.path
    base,ext = os.path.splitext(filename)
    if ext != '.py': return 1        # No idea what the file is. Return OK

    try:
        f = open(filename)
        lines = f.readlines()
        f.close()
    except IOError:
        return 1                     # Couldn't find the file.  Don't worry about it

    fre = re.compile(r'\s*def\s+(t_[a-zA-Z_0-9]*)\(')
    sre = re.compile(r'\s*(t_[a-zA-Z_0-9]*)\s*=')

    counthash = { }
    linen = 1
    noerror = 1
    for l in lines:
        m = fre.match(l)
        if not m:
            m = sre.match(l)
        if m:
            name = m.group(1)
            prev = counthash.get(name)
            if not prev:
                counthash[name] = linen
            else:
                sys.stderr.write("%s:%d: Rule %s redefined. Previously defined on line %d\n" % (filename,linen,name,prev))
                noerror = 0
        linen += 1
    return noerror

# -----------------------------------------------------------------------------
# _funcs_to_names()
#
# Given a list of regular expression functions, this converts it to a list
# suitable for output to a table file
# -----------------------------------------------------------------------------

def _funcs_to_names(funclist,namelist):
    result = []
    for f,name in zip(funclist,namelist):
         if f and f[0]:
             result.append((name, f[1]))
         else:
             result.append(f)
    return result

# -----------------------------------------------------------------------------
# _names_to_funcs()
#
# Given a list of regular expression function names, this converts it back to
# functions.
# -----------------------------------------------------------------------------

def _names_to_funcs(namelist,fdict):
     result = []
     for n in namelist:
          if n and n[0]:
              result.append((fdict[n[0]],n[1]))
          else:
              result.append(n)
     return result

# -----------------------------------------------------------------------------
# _form_master_re()
#
# This function takes a list of all of the regex components and attempts to
# form the master regular expression.  Given limitations in the Python re
# module, it may be necessary to break the master regex into separate expressions.
# -----------------------------------------------------------------------------

def _form_master_re(relist,reflags,ldict,toknames):
    if not relist: return []
    regex = "|".join(relist)
    try:
        lexre = re.compile(regex,re.VERBOSE | reflags)

        # Build the index to function map for the matching engine
        lexindexfunc = [ None ] * (max(lexre.groupindex.values())+1)
        lexindexnames = lexindexfunc[:]

        for f,i in lexre.groupindex.items():
            handle = ldict.get(f,None)
            if type(handle) in (types.FunctionType, types.MethodType):
                lexindexfunc[i] = (handle,toknames[f])
                lexindexnames[i] = f
            elif handle is not None:
                lexindexnames[i] = f
                if f.find("ignore_") > 0:
                    lexindexfunc[i] = (None,None)
                else:
                    lexindexfunc[i] = (None, toknames[f])
        
        return [(lexre,lexindexfunc)],[regex],[lexindexnames]
    except Exception:
        m = int(len(relist)/2)
        if m == 0: m = 1
        llist, lre, lnames = _form_master_re(relist[:m],reflags,ldict,toknames)
        rlist, rre, rnames = _form_master_re(relist[m:],reflags,ldict,toknames)
        return llist+rlist, lre+rre, lnames+rnames

# -----------------------------------------------------------------------------
# def _statetoken(s,names)
#
# Given a declaration name s of the form "t_" and a dictionary whose keys are
# state names, this function returns a tuple (states,tokenname) where states
# is a tuple of state names and tokenname is the name of the token.  For example,
# calling this with s = "t_foo_bar_SPAM" might return (('foo','bar'),'SPAM')
# -----------------------------------------------------------------------------

def _statetoken(s,names):
    nonstate = 1
    parts = s.split("_")
    for i in range(1,len(parts)):
         if not parts[i] in names and parts[i] != 'ANY': break
    if i > 1:
       states = tuple(parts[1:i])
    else:
       states = ('INITIAL',)

    if 'ANY' in states:
       states = tuple(names)

    tokenname = "_".join(parts[i:])
    return (states,tokenname)

# -----------------------------------------------------------------------------
# lex(module)
#
# Build all of the regular expression rules from definitions in the supplied module
# -----------------------------------------------------------------------------
def lex(module=None,object=None,debug=0,optimize=0,lextab="lextab",reflags=0,nowarn=0,outputdir=""):
    global lexer
    ldict = None
    stateinfo  = { 'INITIAL' : 'inclusive'}
    error = 0
    files = { }
    lexobj = Lexer()
    lexobj.lexdebug = debug
    lexobj.lexoptimize = optimize
    global token,input

    if nowarn: warn = 0
    else: warn = 1

    if object: module = object

    if module:
        # User supplied a module object.
        _items = [(k,getattr(module,k)) for k in dir(module)]
        ldict = { }
        for (i,v) in _items:
            ldict[i] = v
        lexobj.lexmodule = module

    else:
        # No module given.  We might be able to get information from the caller.
        try:
            raise RuntimeError
        except RuntimeError:
            e,b,t = sys.exc_info()
            f = t.tb_frame
            f = f.f_back                    # Walk out to our calling function
            if f.f_globals is f.f_locals:   # Collect global and local variations from caller
               ldict = f.f_globals
            else:
               ldict = f.f_globals.copy()
               ldict.update(f.f_locals)

    if optimize and lextab:
        try:
            lexobj.readtab(lextab,ldict)
            token = lexobj.token
            input = lexobj.input
            lexer = lexobj
            return lexobj

        except ImportError:
            pass

    # Get the tokens, states, and literals variables (if any)

    tokens = ldict.get("tokens",None)
    states = ldict.get("states",None)
    literals = ldict.get("literals","")

    if not tokens:
        raise SyntaxError("lex: module does not define 'tokens'")

    if not (isinstance(tokens,list) or isinstance(tokens,tuple)):
        raise SyntaxError("lex: tokens must be a list or tuple.")

    # Build a dictionary of valid token names
    lexobj.lextokens = { }
    if not optimize:
        for n in tokens:
            if not _is_identifier.match(n):
                sys.stderr.write("lex: Bad token name '%s'\n" % n)
                error = 1
            if warn and n in lexobj.lextokens:
                sys.stderr.write("lex: Warning. Token '%s' multiply defined.\n" % n)
            lexobj.lextokens[n] = None
    else:
        for n in tokens: lexobj.lextokens[n] = None

    if debug:
        sys.stdout.write("lex: tokens = '%s'\n" % list(lexobj.lextokens))

    try:
         for c in literals:
               if not isinstance(c,StringTypes) or len(c) > 1:
                    sys.stderr.write("lex: Invalid literal %s. Must be a single character\n" % repr(c))
                    error = 1
                    continue

    except TypeError:
         sys.stderr.write("lex: Invalid literals specification. literals must be a sequence of characters.\n")
         error = 1

    lexobj.lexliterals = literals

    # Build statemap
    if states:
         if not (isinstance(states,tuple) or isinstance(states,list)):
              sys.stderr.write("lex: states must be defined as a tuple or list.\n")
              error = 1
         else:
              for s in states:
                    if not isinstance(s,tuple) or len(s) != 2:
                           sys.stderr.write("lex: invalid state specifier %s. Must be a tuple (statename,'exclusive|inclusive')\n" % repr(s))
                           error = 1
                           continue
                    name, statetype = s
                    if not isinstance(name,StringTypes):
                           sys.stderr.write("lex: state name %s must be a string\n" % repr(name))
                           error = 1
                           continue
                    if not (statetype == 'inclusive' or statetype == 'exclusive'):
                           sys.stderr.write("lex: state type for state %s must be 'inclusive' or 'exclusive'\n" % name)
                           error = 1
                           continue
                    if name in stateinfo:
                           sys.stderr.write("lex: state '%s' already defined.\n" % name)
                           error = 1
                           continue
                    stateinfo[name] = statetype

    # Get a list of symbols with the t_ or s_ prefix
    tsymbols = [f for f in ldict if f[:2] == 't_' ]

    # Now build up a list of functions and a list of strings

    funcsym =  { }        # Symbols defined as functions
    strsym =   { }        # Symbols defined as strings
    toknames = { }        # Mapping of symbols to token names

    for s in stateinfo:
         funcsym[s] = []
         strsym[s] = []

    ignore   = { }        # Ignore strings by state
    errorf   = { }        # Error functions by state

    if len(tsymbols) == 0:
        raise SyntaxError("lex: no rules of the form t_rulename are defined.")

    for f in tsymbols:
        t = ldict[f]
        states, tokname = _statetoken(f,stateinfo)
        toknames[f] = tokname

        if hasattr(t,"__call__"):
            for s in states: funcsym[s].append((f,t))
        elif isinstance(t, StringTypes):
            for s in states: strsym[s].append((f,t))
        else:
            sys.stderr.write("lex: %s not defined as a function or string\n" % f)
            error = 1

    # Sort the functions by line number
    for f in funcsym.values():
        if sys.version_info[0] < 3:
            f.sort(lambda x,y: cmp(func_code(x[1]).co_firstlineno,func_code(y[1]).co_firstlineno))
        else:
            # Python 3.0
            f.sort(key=lambda x: func_code(x[1]).co_firstlineno)

    # Sort the strings by regular expression length
    for s in strsym.values():
        if sys.version_info[0] < 3:
            s.sort(lambda x,y: (len(x[1]) < len(y[1])) - (len(x[1]) > len(y[1])))
        else:
            # Python 3.0
            s.sort(key=lambda x: len(x[1]))

    regexs = { }

    # Build the master regular expressions
    for state in stateinfo:
        regex_list = []

        # Add rules defined by functions first
        for fname, f in funcsym[state]:
            line = func_code(f).co_firstlineno
            file = func_code(f).co_filename

            files[file] = None
            tokname = toknames[fname]

            ismethod = isinstance(f, types.MethodType)

            if not optimize:
                nargs = func_code(f).co_argcount
                if ismethod:
                    reqargs = 2
                else:
                    reqargs = 1
                if nargs > reqargs:
                    sys.stderr.write("%s:%d: Rule '%s' has too many arguments.\n" % (file,line,f.__name__))
                    error = 1
                    continue

                if nargs < reqargs:
                    sys.stderr.write("%s:%d: Rule '%s' requires an argument.\n" % (file,line,f.__name__))
                    error = 1
                    continue

                if tokname == 'ignore':
                    sys.stderr.write("%s:%d: Rule '%s' must be defined as a string.\n" % (file,line,f.__name__))
                    error = 1
                    continue

            if tokname == 'error':
                errorf[state] = f
                continue

            if f.__doc__:
                if not optimize:
                    try:
                        c = re.compile("(?P<%s>%s)" % (fname,f.__doc__), re.VERBOSE | reflags)
                        if c.match(""):
                             sys.stderr.write("%s:%d: Regular expression for rule '%s' matches empty string.\n" % (file,line,f.__name__))
                             error = 1
                             continue
                    except re.error:
                        _etype, e, _etrace = sys.exc_info()
                        sys.stderr.write("%s:%d: Invalid regular expression for rule '%s'. %s\n" % (file,line,f.__name__,e))
                        if '#' in f.__doc__:
                             sys.stderr.write("%s:%d. Make sure '#' in rule '%s' is escaped with '\\#'.\n" % (file,line, f.__name__))
                        error = 1
                        continue

                    if debug:
                        sys.stdout.write("lex: Adding rule %s -> '%s' (state '%s')\n" % (f.__name__,f.__doc__, state))

                # Okay. The regular expression seemed okay.  Let's append it to the master regular
                # expression we're building

                regex_list.append("(?P<%s>%s)" % (fname,f.__doc__))
            else:
                sys.stderr.write("%s:%d: No regular expression defined for rule '%s'\n" % (file,line,f.__name__))

        # Now add all of the simple rules
        for name,r in strsym[state]:
            tokname = toknames[name]

            if tokname == 'ignore':
                 if "\\" in r:
                      sys.stderr.write("lex: Warning. %s contains a literal backslash '\\'\n" % name)
                 ignore[state] = r
                 continue

            if not optimize:
                if tokname == 'error':
                    raise SyntaxError("lex: Rule '%s' must be defined as a function" % name)
                    error = 1
                    continue

                if not tokname in lexobj.lextokens and tokname.find("ignore_") < 0:
                    sys.stderr.write("lex: Rule '%s' defined for an unspecified token %s.\n" % (name,tokname))
                    error = 1
                    continue
                try:
                    c = re.compile("(?P<%s>%s)" % (name,r),re.VERBOSE | reflags)
                    if (c.match("")):
                         sys.stderr.write("lex: Regular expression for rule '%s' matches empty string.\n" % name)
                         error = 1
                         continue
                except re.error:
                    _etype, e, _etrace = sys.exc_info()
                    sys.stderr.write("lex: Invalid regular expression for rule '%s'. %s\n" % (name,e))
                    if '#' in r:
                         sys.stderr.write("lex: Make sure '#' in rule '%s' is escaped with '\\#'.\n" % name)

                    error = 1
                    continue
                if debug:
                    sys.stdout.write("lex: Adding rule %s -> '%s' (state '%s')\n" % (name,r,state))

            regex_list.append("(?P<%s>%s)" % (name,r))

        if not regex_list:
             sys.stderr.write("lex: No rules defined for state '%s'\n" % state)
             error = 1

        regexs[state] = regex_list


    if not optimize:
        for f in files:
           if not _validate_file(f):
                error = 1

    if error:
        raise SyntaxError("lex: Unable to build lexer.")

    # From this point forward, we're reasonably confident that we can build the lexer.
    # No more errors will be generated, but there might be some warning messages.

    # Build the master regular expressions

    for state in regexs:
        lexre, re_text, re_names = _form_master_re(regexs[state],reflags,ldict,toknames)
        lexobj.lexstatere[state] = lexre
        lexobj.lexstateretext[state] = re_text
        lexobj.lexstaterenames[state] = re_names
        if debug:
            for i in range(len(re_text)):
                 sys.stdout.write("lex: state '%s'. regex[%d] = '%s'\n" % (state, i, re_text[i]))

    # For inclusive states, we need to add the INITIAL state
    for state,type in stateinfo.items():
        if state != "INITIAL" and type == 'inclusive':
             lexobj.lexstatere[state].extend(lexobj.lexstatere['INITIAL'])
             lexobj.lexstateretext[state].extend(lexobj.lexstateretext['INITIAL'])
             lexobj.lexstaterenames[state].extend(lexobj.lexstaterenames['INITIAL'])

    lexobj.lexstateinfo = stateinfo
    lexobj.lexre = lexobj.lexstatere["INITIAL"]
    lexobj.lexretext = lexobj.lexstateretext["INITIAL"]

    # Set up ignore variables
    lexobj.lexstateignore = ignore
    lexobj.lexignore = lexobj.lexstateignore.get("INITIAL","")

    # Set up error functions
    lexobj.lexstateerrorf = errorf
    lexobj.lexerrorf = errorf.get("INITIAL",None)
    if warn and not lexobj.lexerrorf:
        sys.stderr.write("lex: Warning. no t_error rule is defined.\n")

    # Check state information for ignore and error rules
    for s,stype in stateinfo.items():
        if stype == 'exclusive':
              if warn and not s in errorf:
                   sys.stderr.write("lex: Warning. no error rule is defined for exclusive state '%s'\n" % s)
              if warn and not s in ignore and lexobj.lexignore:
                   sys.stderr.write("lex: Warning. no ignore rule is defined for exclusive state '%s'\n" % s)
        elif stype == 'inclusive':
              if not s in errorf:
                   errorf[s] = errorf.get("INITIAL",None)
              if not s in ignore:
                   ignore[s] = ignore.get("INITIAL","")


    # Create global versions of the token() and input() functions
    token = lexobj.token
    input = lexobj.input
    lexer = lexobj

    # If in optimize mode, we write the lextab
    if lextab and optimize:
        lexobj.writetab(lextab,outputdir)

    return lexobj

# -----------------------------------------------------------------------------
# runmain()
#
# This runs the lexer as a main program
# -----------------------------------------------------------------------------

def runmain(lexer=None,data=None):
    if not data:
        try:
            filename = sys.argv[1]
            f = open(filename)
            data = f.read()
            f.close()
        except IndexError:
            sys.stdout.write("Reading from standard input (type EOF to end):\n")
            data = sys.stdin.read()

    if lexer:
        _input = lexer.input
    else:
        _input = input
    _input(data)
    if lexer:
        _token = lexer.token
    else:
        _token = token

    while 1:
        tok = _token()
        if not tok: break
        sys.stdout.write("(%s,%r,%d,%d)\n" % (tok.type, tok.value, tok.lineno,tok.lexpos))

# -----------------------------------------------------------------------------
# @TOKEN(regex)
#
# This decorator function can be used to set the regex expression on a function
# when its docstring might need to be set in an alternative way
# -----------------------------------------------------------------------------

def TOKEN(r):
    def set_doc(f):
        if hasattr(r,"__call__"):
            f.__doc__ = r.__doc__
        else:
            f.__doc__ = r
        return f
    return set_doc

# Alternative spelling of the TOKEN decorator
Token = TOKEN

