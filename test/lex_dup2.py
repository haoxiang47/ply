# lex_token.py
#
# Duplicated rule specifiers

import sys
sys.path.insert(0,"..")

import ply.lex as lex

tokens = [
    "PLUS",
    "MINUS",
    "NUMBER",
    ]

t_PLUS = r'\+'
t_MINUS = r'-'
def t_NUMBER(t):
    r'\d+'
    pass

def t_NUMBER(t):
    r'\d+'
    pass

def t_error(t):
    pass

sys.tracebacklimit = 0

lex.lex()


