# ARM firmware analysis console for Magic Lantern
# http://magiclantern.wikia.com/wiki/GPL_Tools/ARM_console
#
# (C) 2010 Alex Dumitrache <broscutamaker@gmail.com>
# License: GPL
#
# Module emusym: symbolic ARM code emulation (based on SymPy)

from idapy import *
import idapy
import time
from copy import copy, deepcopy
import sys
import pydot, string
import ctypes
import sympy
from sympy import *
from sympy.core.cache import * 
import re
import funargs
from funargs import void, ptr
from sympy.printing.printer import Printer
from sympy.printing.str import StrPrinter
#from pprint >> log, import pprint

guess_unknown_structs = 0

log = open("emusym.log", "w")
clog = open("emusym-c.log", "w")

def resetLog():
    global log
    log.close()
    log = open("emusym.log", "w")

    global clog
    clog.close()
    clog = open("emusym-c.log", "w")

Operands = {"ADD": "+", 
            "SUB": "-", 
            "RSB": "*rsb*", 
            "LSL": "*lsl*", 
            "LSR": "*lsr*", 
            "ASL": "*asl*", 
            "ASR": "*asr*", 
            "MUL": "*", 
            "AND": "*andop*",
            "ORR": "*orop*",
            "EOR": "*xor*",
            "BIC": "*bic*",
            "CMP": "-", 
            "CMN": "+",
            "TST": "*andop*",
            "TEQ": "*xor*"
            }
BHMask = {'B': 0xFF, 'H': 0xFFFF}

# int printed as hex
#~ class uint32(int):
   #~ def __str__(self):
        #~ return "0x%X" % ctypes.c_uint32(self).value
   #~ def __repr__(self):
        #~ return "0x%X" % ctypes.c_uint32(self).value

def GuessFunction(start, quick = False):

    if GetMnef(start) == "B":
        print "j_something"
        return start + 4
    if GetMnem(start)=="BX" and GetOpnd(start,0) == "LR":
        print "bx lr (nullsub)"
        return start + 4
    if GetMnef(start) not in idapy.instructions_allowed_for_func_start:
        print "first instruction invalid"
        return
    if start in idapy._d.STRMASK:
        print "first instruction is inside a string"
        return
    
    endq = start
    while maybeFuncStart(endq + 4):
        endq += 4
    undefined = 0
    while not maybeFuncStart(endq + 4):
        endq += 4
        if not GetMnem(endq):
            undefined += 1
        else:
            undefined = 0
        if undefined > 100:
            print "quick guess: this doesn't look like code..."
            endq = None
            break
        if endq - start > 30000:
            print "quick guess: this is huge..."
            endq = None
            break
    
    if quick:
        end = endq
        if endq: print "Size (quick guess):", end+4-start
        return end
    # this is slow... 
    try: 
        CP = find_code_paths(start,timeout=0.1)
    except Exception: 
        if endq:
            print "time out, using quick guess"
            end = endq
            print "Size (quick guess):", end+4-start
            return end
        else:
            return
    end = 0
    for cp in CP:
        end = max(end, max(cp)[0])
    if endq: print "Size (quick guess):", endq+4-start
    print "Size (code paths) :", end+4-start
    if endq and end - endq > 1000:
        print "Using quick guess"
        return endq # full guess overestimate?
    print "Using code path guess"
    return end


def IsReturn(ea):
    dis = GetDisasmQ(ea).upper()
    if dis.startswith("LDM") and "PC" in GetOpnd(ea,1):
        print >> log, "return (LDM changes PC)"
        return True
    if dis.startswith("POP") and "PC" in GetOpnds(ea):
        print >> log, "return (POP changes PC)"
        return True
    if GetMnem(ea) == "RET":
        print >> log, "return (RET)"
        return True
    if GetMnem(ea) == "MOV" and GetOpnd(ea,0) == "PC":
        print >> log, "return (MOV changes PC)"
        return True
    if GetMnem(ea)=="BX" and GetOpnd(ea,0) == "LR":
        print >> log, "return (BX LR)"
        return True
    return False


def split_code_path_ea_cond(cpf):
    cp = []
    cf = []
    for elem in cpf:
        if type(elem) == tuple:
            ea,condf = elem
        else:
            ea,condf = elem,""
        cp.append(ea)
        cf.append(condf)
    return cp,cf
def cp_only(cpf):
    cp,cf = split_code_path_ea_cond(cpf)
    return cp
def cf_only(cpf):
    cp,cf = split_code_path_ea_cond(cpf)
    return cf

def get_neighbour_instructions(cp,ea):
    
    start = 0
    end = 0
    for i,a in enumerate(cp):
        if a == ea:
            break
        if ChangesFlags(a):
            start = i + 1

    for i,a in enumerate(cp):
        if i > start:
            if ChangesFlags(a):
                end = i
                break
    return cp[start:end]
    
def strip_wrong_branches(cp):
    CP = copy(cp)
    cpx = cp + [cp[-1] + 4]
    for ea,next_ea in zip(cpx[:-1], cpx[1:]):
        if GetMnem(ea) == "B":
            if GetOperandValue(ea,0) != next_ea:
                CP.remove(ea)
                if GetCondSuffix(ea): # will remove neighbor instructions with similar condition flags
                    #~ print get_neighbour_instructions(cp,ea)
                    for a in get_neighbour_instructions(cp,ea): # fixme: there may be still some tricky cases uncovered...
                        if a != ea and GetCondSuffix(a) == GetCondSuffix(ea):
                            print a, GetDisasm(a)
                            CP.remove(a)
    return CP

def add_branch_info(cp):
    #~ print "add_branch_info"
    CP = find_code_paths(cp[0], single_ref_codepath = cp)
    pprint(CP)
    for c in CP:
        co = cp_only(c)
        #~ print "co",co
        #~ print "cp",cp
        #~ print "======"
        #~ emusym.print_cp(co)
        l = min(len(co), len(cp))
        if co[:l] == cp[:l]:
            return c[:l]
    print "bad codepath?"
    print_cp(cp)
    pprint(CP)
    print
    print "cp_debug = ", cp_only(cp)
    

# returns:
# * a list of code paths with flags (cpf)
# * a code path is a list of (addr, condition_flags)

timeout_deadline = time.time() + 10000
def find_code_paths(ea, startAddr = None, prefix=[], branches=[], timeout=10000, single_ref_codepath = None):
    global timeout_deadline
    if timeout:
        timeout_deadline = time.time() + timeout
    else:
        if time.time() > timeout_deadline:
            raise Exception, "timeout"
    
    #print "find_code_paths(%X,%s,%s)" % (ea, prefix, branch)
    print >> log, "find_code_paths(%X,%s,%s)" % (ea, prefix, branches)
    CP = [] # a list of code paths
    cpf = copy(prefix) # a code path: a list of (addr, condition_flags)

    # branches: list of string with what branch(es) to take
    # branchx: includes branches and the opposite of the branches
    branchx = []
    for b in branches:
        branchx.append(b)
        branchx.append(OppositeSuffix(b))
        
    #~ try: 
        #~ E = list(FuncItems(ea))
    #~ except: 
        #~ E = range(ea,ea+10000,4)
    
    flagsDirty = False
    branchDone = False
    kb = 0
    
    if startAddr: 
        ea = startAddr
        #~ i0 = E.index(startAddr)
    #~ else: 
        #~ i0 = 0

    if single_ref_codepath is not None:
        #~ print ea
        #~ print "ref ", [hex(i) for i in single_ref_codepath]
        chk = cp_only(cpf)
        #~ print "chk ", [hex(i) for i in chk]
        for a,b in zip(chk,single_ref_codepath): # compare prefixes
            if a != b:
                #~ print "mismatch: ", hex(a), hex(b)
                return [[(-1,-1)]]
        #~ print "ok"
        if len(chk) > len(single_ref_codepath):
            #~ print cpf
            CP.append(cpf)
            return CP

    #~ ea = E[i0]
    while True:
    #for ie in range(i0, len(E)):   # first instruction is either a branch or the first instruction
        #~ print ea
        print >> log, "%X"%ea, GetDisasmQ(ea) 
        #time.sleep(0.1)
        #~ print "%X"%ea, GetDisasmQ(ea)
            
        m = GetMnem(ea)
        if not m:
            print "undefined instruction"
            return CP
        suffix = GetCondSuffix(ea)
        if not suffix:             # regular instruction, just execute it
            cpf.append((ea,branches))
            if ChangesFlags(ea):
                print >> log, "changes flags"
                flagsDirty = True
                branchDone = True
                branches = []
                branchx = []
            #~ print >> log, >> sys.stderr, m
            if m == "B":
                newAddr = GetOperandValue(ea, 0)
                print >> log, "new addr: 0x%x" % newAddr
                #~ print "new addr: 0x%x" % newAddr
                if isFuncStart(newAddr) or maybeFuncStart(newAddr):
                    print >> log, "Tail call: ", GetDisasmQ(ea)
                    break
                else:
                    if newAddr in cp_only(cpf):
                        print >> log, "loop"
                        print >> log, cp_only(cpf)
                        cpf = cpf + [cpf[cp_only(cpf).index(newAddr)]]
                        #~ print "loop"
                        break
                    ea = newAddr
                    continue
            if IsReturn(ea):
                print >> log, "RETURN at %x" % ea
                break
            if ChangesPC(ea):
                print "Jumpy?", hex(ea), GetDisasm(ea), GetMnef(ea)
                if GetMnef(ea) == "ADDLS":
                    for off in range(500):
                        newAddr = ea + off * 4 + 8
                        CP += find_code_paths(ea, newAddr, cpf, ["EQ%d" % off], None, single_ref_codepath)
                        if GetMnem(newAddr) not in ["B", "BX", "POP"]: break
                elif GetMnef(ea) == "LDRLS":
                    for off in range(500):
                        newAddr = ea + off * 4 + 8
                        newAddr = idapy._d.ROM[newAddr]
                        if newAddr not in idapy._d.ROM: break
                        print hex(newAddr)
                        CP += find_code_paths(ea, newAddr, cpf, ["EQ%d" % off], None, single_ref_codepath)
                else:
                    print "dunno...", hex(ea), GetDisasm(ea)
                    CP.append(cpf)
                return CP
                    
        elif suffix in branchx:
            print >> log, "same suffix:", suffix, branches
            if flagsDirty: 
                print >> log, "flags dirty => new branch"
                # new branch with same suffix (flags changed?)
                CP += find_code_paths(ea, ea, cpf, [OppositeSuffix(suffix)], None, single_ref_codepath)
                CP += find_code_paths(ea, ea, cpf, [suffix], None, single_ref_codepath)
                return CP
            else:
                print >> log, "flags clean => same branch"
                if suffix in branches:
                    print >> log, "condition ok => adding to path"
                    cpf.append((ea,branches))
                    if ChangesFlags(ea):
                        print >> log, "changes flags"
                        flagsDirty = True
                        branchDone = True
                        branches = []
                        branchx = []
                    if m == "B":
                        newAddr = GetOperandValue(ea, 0)
                        print >> log, "new addr: %x" % newAddr
                        if isFuncStart(newAddr) or maybeFuncStart(newAddr):
                            print >> log, "Tail call: ", GetDisasmQ(ea)
                            break
                        ea = newAddr
                        if newAddr in cp_only(cpf):
                            print >> log, "loop"
                            print >> log, cp_only(cpf)
                            cpf = cpf + [cpf[cp_only(cpf).index(newAddr)]]
                            #print "loop"
                            break
                        continue
                    if IsReturn(ea):
                        print >> log, "RETURN at %x" % ea
                        break
                    if ChangesPC(ea):
                        print "Jumpy?", hex(ea), GetDisasm(ea), GetMnef(ea)
                        if GetMnef(ea) == "ADDLS":
                            for off in range(500):
                                newAddr = ea + off * 4 + 8
                                CP += find_code_paths(ea, newAddr, cpf, ["EQ%d" % off], None, single_ref_codepath)
                                if GetMnem(newAddr) not in ["B", "BX", "POP"]: break
                        elif GetMnef(ea) == "LDRLS":
                            for off in range(500):
                                newAddr = ea + off * 4 + 8
                                newAddr = idapy._d.ROM[newAddr]
                                if newAddr not in idapy._d.ROM: break
                                print hex(newAddr)
                                CP += find_code_paths(ea, newAddr, cpf, ["EQ%d" % off], None, single_ref_codepath)
                        else:
                            print "dunno...", hex(ea), GetDisasm(ea)
                            CP.append(cpf)
                        return CP
                else:
                    print >> log, "opposite condition => skipping"
                    pass
        else: # some other suffix
            print >> log, "some other suffix => expanding current branch (suffix=%s, branches=%s)" % (suffix,branches)
            # new branch with another suffix
            CP += find_code_paths(ea, ea, cpf, branches + [OppositeSuffix(suffix)], None, single_ref_codepath)
            CP += find_code_paths(ea, ea, cpf, branches + [suffix], None, single_ref_codepath)
            return CP


        # next instr
        #~ try: ea = E[E.index(ea) + 1]
        #~ except IndexError: break
        ea += 4

    CP.append(cpf)
    return CP


condit = ""
# symbolic representation of the code
#====================================

def inden(x):
    return "    " + x.replace("\n", "\n    ")

def cond_str(cf,condit,P):
    
    m = re.match("EQ([0-9]+)", cf)
    if m:
        value = int(m.groups()[0])
        return cond_str("EQ", condit - value, P)
    
    if condit.is_Atom or type(condit) == MEM:
        condit = P.doprint(condit)
        assert cf != "NE_and_EQ"
        if cf.startswith("NE_and_"): cf = cf[7:]
        if cf == "EQ": return "%s == 0" % condit
        elif cf == "NE": return "%s != 0" % condit
        elif cf in ["GT", "HI"]: return "%s > 0" % condit
        elif cf in ["MI", "LT", "LO", "CC"]: return "%s < 0" % condit
        elif cf in ["CC","HS", "PL", "GE"]: return "%s >= 0" % condit
        elif cf in ["LS", "LE"]: return "%s <= 0" % condit
        
    if type(condit) == Add and len(condit.args) == 2:
        a = P.doprint(condit.args[1])
        b = P.doprint(-condit.args[0])
        ma = P.doprint(-condit.args[1])
        mb = P.doprint(condit.args[0])
        #~ print a,b,ma,mb
        assert cf != "NE_and_EQ"
        if cf.startswith("NE_and_"): cf = cf[7:]
        if cf == "EQ": 
            pl = "%s == %s" % (a,b)
            mi = "%s == %s" % (ma,mb)
            return mi if a.startswith("-") and b.startswith("-") else pl
        elif cf in ["GT", "HI"]: return "%s > %s" %  (a,b)
        elif cf in ["MI", "LT", "LO", "CC"]: return "%s < %s" %  (a,b)
        elif cf in ["CC","HS", "PL", "GE"]: return "%s >= %s" %  (a,b)
        elif cf in ["LS", "LE"]: return "%s <= %s" %  (a,b)

def cond_eval(cf,condit):
    if condit.is_Atom:
        try: condit = int(condit)
        except: return
        
        if cf == "EQ": return condit == 0
        elif cf == "NE": return condit != 0
        elif cf in ["GT", "NE_and_GT"]: return condit > 0
        elif cf in ["LT", "NE_and_LT"]: return condit < 0
        elif cf in ["GE", "NE_and_GE"]: return condit >= 0
        elif cf in ["LE", "NE_and_LE"]: return condit <= 0
        
    if type(condit) == Add and len(condit.args) == 2:
        try:
            a = int(condit.args[1])
            b = int(-condit.args[0])
            ma = int(-condit.args[1])
            mb = int(condit.args[0])
        except:
            return
        if cf == "EQ": 
            return a == b
        elif cf == "NE": return a != b
        elif cf in ["GT", "NE_and_GT"]: return a > b
        elif cf in ["LT", "NE_and_LT"]: return a < b
        elif cf in ["GE", "NE_and_GE"]: return a >= b
        elif cf in ["LE", "NE_and_LE"]: return a <= b
    
# a single IF branch (or rung)
class IFB(Function):
    pass

def setSimpFlags(ret, ret_reverse):
    #~ global simp_ret, simp_ret_reverse
    sympy.simp_ret = ret
    sympy.simp_ret_reverse = ret_reverse
    clear_cache()
# first init
try:
    a = sympy.simp_ret
except:
    #~ print "init simp flags"
    setSimpFlags(True,True)
    a = sympy.simp_ret
    #~ print "ok"

# if instruction: IF(1==2, IFB("EQ", SEQ(...)), IFB("NE", SEQ(...)))
class IF(Function):
    @classmethod
    def eval(self,test,a=None,b=None,*args):
        #~ print "if eval"
        #
        # if TRUE: abc => abc
        #
        #
        if a and str(a.args[0]) == "TRUE":
            #~ print "extract true"
            return SEQ(a.args[1],
                       IF(test, b, *args),
                     )  


        # if a:                      x
        #     x                      if a:
        #     y                           y
        # if not a:            =>    if not a:
        #     x                           z
        #     z

        # if a:                      
        #     x                      if a:
        #     z                           x
        # if not a:            =>    if not a:
        #     y                           y
        #     z                      z

        if a and b and not args:
            ca = str(a.args[0])
            cb = str(b.args[0])
            if (ca == OppositeSuffix(cb)) and (type(a.args[1]) == SEQ) and (type(b.args[1]) == SEQ):

                try:
                    lasta = a.args[1].args[-1]
                    lastb = b.args[1].args[-1]
                except IndexError:
                    return
                
                if sympy.simp_ret:
                    if sympy.simp_ret_reverse:
                        if type(lastb) == RETURN:
                            #~ print "retsimp b"
                            return SEQ(IF(test, IFB(b.args[0], SEQ(*b.args[1].args)),
                                            ),
                                       SEQ(*a.args[1].args))

                        if type(lasta) == RETURN:
                            #~ print "retsimp"
                            return SEQ(IF(test, IFB(a.args[0], SEQ(*a.args[1].args)),
                                            ),
                                       SEQ(*b.args[1].args))
                    else:
                        if type(lastb) == RETURN:
                            #~ print "retsimp b"
                            return SEQ(IF(test, IFB(b.args[0], SEQ(*b.args[1].args)),
                                            ),
                                       SEQ(*a.args[1].args))

                        if type(lasta) == RETURN:
                            #~ print "retsimp"
                            return SEQ(IF(test, IFB(a.args[0], SEQ(*a.args[1].args)),
                                            ),
                                       SEQ(*b.args[1].args))


                #~ try:
                    #~ lasta = a.args[1].args[-1]
                    #~ lastb = b.args[1].args[-1]
                #~ except IndexError:
                    #~ return
                if P.doprint(lasta)==P.doprint(lastb):
                    #~ print "common last"
                    return SEQ(IF(test, IFB(a.args[0], SEQ(*a.args[1].args[:-1])),
                                    IFB(b.args[0], SEQ(*b.args[1].args[:-1]))),
                               lasta)



                try:
                    firsta = a.args[1].args[0]
                    firstb = b.args[1].args[0]
                except IndexError:
                    return
                if P.doprint(firsta)==P.doprint(firstb):
                    #~ print "common first"
                    return SEQ(firsta, 
                               IF(test, IFB(a.args[0], SEQ(*a.args[1].args[1:])),
                                    IFB(b.args[0], SEQ(*b.args[1].args[1:]))),
                             )


class SEQ(Function):
        
    @classmethod
    def eval(self, *args):
        found = False
        for a in args:
            if type(a) == SEQ:
                found = True
        if not found: return
        
        A = []
        for a in args:
            if type(a) == SEQ:
                A += a.args
            else:
                A.append(a)
        return SEQ(*A)

#~ voidfuncs = ["assert_0", "DebugMsg"]
abortfuncs = ["assert_0", "assert", "TH_assert"]

#~ def isVoidFunc(ea):
    #~ return GetFunctionName(ea) in voidfuncs

def isAbortFunc(ea):
    return GetFunctionName(ea) in abortfuncs



def RetName(funcaddr, calladdr, funcname=None):
    if funcname is None:
        funcname = GetFunctionName(funcaddr)
        if funcname is None:
            funcname = GetName(funcaddr)
        if funcname is None:
            funcname = "FUNC(%s)" % STR(funcaddr)
    retname = "ret_%s_%s" % (funcname, "%X"%int(calladdr))
    return retname

class CALL(Function):
    pass
    
class RETURN(Function):
    pass

#~ class MEMWRITE(Function):
    #~ pass

#~ class MEMREAD(Function):
    #~ pass

class REGWRITE(Function):
    pass

class JUMP(Function):
    pass
    
class REGREAD(Function):
    pass



class DecoPrinter(StrPrinter):

    def _print_Integer(self,expr):
        return STR(expr)

    def _print_int(self,expr):
        return self._print_Integer(expr)
        
    def _print_long(self,expr):
        return self._print_Integer(expr)
    
    def _ptr(self,expr):
        addr = expr.args[0]
        try: return "*0x%s" % hex(int(addr))
        except: return "*(%s)" % self._print(addr)

    def _get_struct_name(self, base):
        return idapy._d.A2N.get(base, "struct_0x%x" % base).split(".")[0]
    
    def _get_struct_off_name(self, base, off):
        if base+off in idapy._d.A2N:
            structname = self._get_struct_name(base)
            fieldname = idapy._d.A2N[base+off]
            if fieldname.startswith(structname + "."):
                fieldname = fieldname[len(structname):]
                fieldname = fieldname.strip("._")
            else:
                if not off:
                    return ".off_0x" + hex(off) + (" /*0x%s*/" % hex(base+off))
            return "." + fieldname + (" /*off_0x%s, 0x%s*/" % (hex(off), hex(base+off)))
        else:
            return ".off_0x" + hex(off) + (" /*0x%s*/" % hex(base+off))
        
    def _print_Add(self,expr):
        if len(expr.args) == 2 and type(expr.args[1]) == STRUCTPTR:
            try:
                base = int(expr.args[1].args[0])
                off = int(expr.args[0])
                assert off > 0 and off < 0x1000
            except:
                try: return super(DecoPrinter,self)._print_Add(expr)
                except: return str(expr)
            return "&(" + self._get_struct_name(base) + self._get_struct_off_name(base, off) + ")"
        else:
            try: return super(DecoPrinter,self)._print_Add(expr)
            except: return str(expr)

    def _print_MEM(self,expr):
        addr = expr.args[0]
        if type(addr) == Add and len(addr.args) == 2:
            if type(addr.args[1]) in [STRUCTPTR, STRUCTPTR_MAYBE]:
                try:
                    base = int(addr.args[1].args[0])
                    off = int(addr.args[0])
                    assert off > 0 and off < 0x1000
                except: return self._ptr(expr)
                return self._get_struct_name(base) + self._get_struct_off_name(base, off)
            else:
                try: 
                    off = int(addr.args[0])
                    assert off > 0 and off < 0x1000
                except: return self._ptr(expr)
                struct = addr.args[1]
                if struct.is_Atom:
                    return ("%s->off_0x" % self._print(struct)) + hex(off)# + (" /*%s*/" % self._print(struct+off))
                return ("(%s)->off_0x" % self._print(struct)) + hex(off)# + (" /*%s*/" % self._print(struct+off))
                
        if type(addr) == STRUCTPTR:
            try: base = int(addr.args[0])
            except: return self._ptr(expr)
            off = 0
            n = idapy._d.A2N.get(base, "struct_0x%x" % base)
            return n + ("" if "." in n else ".off_0")
        
        return self._ptr(expr)

    def _print_MEMWRITE(self, expr):
        return "%s = %s" % (self._print_MEM(expr), self._print(expr.args[1]))

    def _print_SEQ(self,expr):
        A = []
        for a in expr.args:
            A.append(self._print(a))
        return string.join(A, "\n")

    def _print_IF(self,expr):
        A = []
        global condit
        args = copy(list(expr.args[1:]))
        for a in args:
            condit = expr.args[0]
            #~ print condit
            A.append(self._print(a))
        return string.join(A, "\n")

    def _print_IFB(self,expr):
        #~ if str(self.args[0]) == "TRUE":
            #~ return "\n" + str(self.args[1])
        #~ if str(self.args[0]) == "zELSE":
            #~ return "else:\n%s" % (inden(str(self.args[1])))
        cf = self._print(expr.args[0])
        #~ return "if %s:\n" % (cf)
        if expr.args[1].args: # if it does something... (branch not empy)
            #~ ce = cond_eval(cf, condit)
            #~ if ce is not None:
                #~ if not ce: return "(false)"
                
            cs = cond_str(cf, condit, self)
            if cs:
                return "if %s /*%s*/:\n%s" % (cs, cf, inden(self._print(expr.args[1])))
                
            return "if %s(%s):\n%s" % (cf, self._print(condit), inden(self._print(expr.args[1])))
        return ""

    def _print_STRUCTx(self,expr):
        addr = expr.args[0]
        off = expr.args[1]
        try: return idapy._d.A2N[int(addr)] + ".off_0x" + hex(off)
        except:
            return "STRUCT(%s+%s)" % (hex(int(addr)),hex(int(off)))
            #~ except: return "STRUCT(%s)" % addr

    def _print_STRUCTPTR(self,expr):
        addr = expr.args[0]
        prefix = "&" if addr < 0x40000000 else ""
        try:
            addr = int(addr) 
            return prefix + self._get_struct_name(addr) + self._get_struct_off_name(addr, 0)
        except: 
            raise
            #~ return str(expr)
            #~ except: return "STRUCT(%s)" % addr

    #~ def _print_STRUCTPTR_MAYBE(self,expr):
        #~ try: return "0x" + hex(expr.args[0])
        #~ except: return self._print(expr.args[0])

    def _print_AND(self,expr):
        a = expr.args[0]
        b = expr.args[1]
        try: a = "0x%X" % ctypes.c_uint32(int(a)).value
        except: a = self._print(a)

        try: b = "0x%X" % ctypes.c_uint32(int(b)).value
        except: b = self._print(b); # raise
        return "(%s & %s)" % (a,b)

    def _print_CALL(self,expr):
        calladdr, funcaddr = expr.args[0], expr.args[1]
        funcname = None
        sig = funargs.FSig(None, None, None, None, ret=None)
        try: 
            funcaddr = int(funcaddr)
            funcname = GetFunctionName(funcaddr)
            sig = funargs.getFuncSignature(funcaddr)
        except: pass

        if funcname is None:
            funcname = GetName(funcaddr)
        if funcname is None:
            funcname = "FUNC(%s)" % self._print(funcaddr)

        retname = RetName(funcaddr, calladdr, funcname)

        #~ print calladdr , funcaddr, funcname, retname
        
        call_line = funcname + "("
        for i,(name,typ) in enumerate(sig.args):
            try: v = expr.args[i+2]
            except: 
                call_line += "..."
                continue
                
            if name: call_line += "%s=" % name

            try: v = int(v)
            except: pass
            typ_eq_hex = type(typ).__name__ == 'function' and typ.func_name == "hex"
            #~ print name,typ,v,hex,typ==hex
            #~ call_line += "(" + type(v).__name__ + ")"
            if type(v) in [int,long]:
                if typ is None: 
                    if GetName(v):
                        call_line += GetName(v)
                    else:
                        call_line += disasm.guess_data(idapy._d, v)
                elif typ==int: call_line += "%d" % v
                elif typ_eq_hex: call_line += "0x" + hex(v)
                elif typ==str: call_line += "%s" % repr(GetString(v))
                elif typ==ptr: call_line += "&(%s)" % P.doprint(MEM(v))
            else:
                if typ==ptr: 
                    call_line += "&(%s)" % P.doprint(MEM(v))
                else:
                    call_line += self._print(v)
            if i < len(sig.args)-1:
                call_line += ", "
        call_line += ")"
        
        #~ if str(func) in voidfuncs:
            #~ return "%s(%s, %s, %s, %s)" % (func, STR(arg0), STR(arg1), STR(arg2), STR(arg3))
        #~ return "%s(%s, %s, %s, %s) => " % (func, STR(arg0), STR(arg1), STR(arg2), STR(arg3), )
        if sig.ret != void:
            call_line += " => %s" % retname
        return call_line

    def _print_RETURN(self, expr):
        return "return " + self._print(expr.args[0])

P = DecoPrinter()

# code tree
CTree = []
CurrPos = CTree
IfPending = False
# this is for stupid tests like:
# CMP a,b
# ADD x,y   # regardless of the test
# MOVEQ ... # and IF starts from here...
# MOVNE ...
# => I'll consider ADD(x,y) as being BEFORE (OUTSIDE) the if

def AddInstr(instr):
    assert(instr is not None)
    cond = tuple(ARM.currentBranchFlags)
    #~ global IfPending
    #~ if cond and IfPending:                # we have the condition ready => IF starts from here
        #~ IfPending = False
        #~ condition = ARM.condFlags
        #~ ife = {"condition": condition}
        #~ AddInstr(ife)
        #~ global CurrPos
        #~ CurrPos = ife


    if type(CurrPos) == list:
        CurrPos.append(instr)
    elif type(CurrPos) == dict:
        if cond in CurrPos:
            CurrPos[cond].append(instr)
        else:
            CurrPos[cond] = [instr]
    else:
        raise Exception, "bad CurrentPos"

def AddIf():
    
    #~ global IfPending
    #~ cond = tuple(ARM.currentBranchFlags)
    #~ if cond and IfPending:                # we have the condition ready => IF starts from here
        #~ IfPending = False
        condition = ARM.condFlags
        ife = {"condition": condition}
        AddInstr(ife)
        global CurrPos
        CurrPos = ife

    #~ IfPending = True


def make_symbolic_tree(T):
    if type(T) == list:
        newT = []
        for t in T:
            newT.append(make_symbolic_tree(t))
        return SEQ(evaluate=False, *newT)
    elif type(T) == dict:
        #~ print "dict:", T
        branches = []
        for cond, actions in T.iteritems():
            if type(cond) == tuple:
                #print "cond:", cond, actions
                cond = string.join(list(cond), "_and_")
                if not cond: cond = "TRUE"
                ifb = IFB(cond, make_symbolic_tree(actions), evaluate=False)
                #~ print "ifb:", ifb, branches
                branches.append(ifb)
                #~ print "after ifb:", ifb, branches
            else:
                ifcond = actions
        #~ print "br:", branches
        args = [ifcond] + branches
        #~ print args
        return IF(evaluate=False, *args)
    return T


def create_graph(CP, filename="emusym.svg"):
    graph = pydot.Dot(graph_type='digraph')
    edges = []

    # the "happy path" (the normal path of execution) is considered to be the longest one (just a heuristic)
    CP = sorted(CP, key=lambda x: -len(x))

    #input and output degrees for nodes
    degi = {}
    dego = {}

    nodes = {}
    edges = {}
    
    W,COLOR = {},{}
    for icp,cpf in enumerate(CP):
        cp = cp_only(cpf)
        for i in range(1,len(cp)):
            ea = cp[i-1]
            eb = cp[i]
            W[(ea,eb)] = max(W.get((ea,eb),0), len(cp)**2)
            COLOR[(ea,eb)] = COLOR.get((ea,eb), "red" if icp==0 else "blue")
            #W[(ea,eb)] = 1 if icp==0 else 0
            sa = '"%s"' % (GetDisasm(ea).replace('"', "''"))
            sb = '"%s"' % (GetDisasm(eb).replace('"', "''"))
            if GetMnem(ea) == "B" and i < len(cp)-1: sa = '"%s %x"' % (GetFirstWord(GetDisasm(ea)), GetOperandValue(ea,0))
            if GetMnem(eb) == "B" and i < len(cp)-1: sb = '"%s %x"' % (GetFirstWord(GetDisasm(eb)), GetOperandValue(eb,0))
            sa = filter_non_printable(sa).replace("{",r"\{").replace("}",r"\}")
            sb = filter_non_printable(sb).replace("{",r"\{").replace("}",r"\}")

            if ea not in nodes:
                nodes[ea] = pydot.Node("_%X"%ea, label=sa, shape="box")
            if eb not in nodes:
                nodes[eb] = pydot.Node("_%X"%eb, label=sb, shape="box")
            if (ea,eb) not in edges:
                edges[(ea,eb)] = pydot.Edge(nodes[ea], nodes[eb], color=COLOR[(ea,eb)], weight=str(W[(ea,eb)]))
                degi[ea] = degi.get(ea, 0) + 1
                dego[eb] = dego.get(eb, 0) + 1

    
    # merge nodes (can be commented out)
    for (ea,eb) in copy(edges):
        if degi[ea] == 1 and dego[eb] == 1:
            na,nb = nodes[ea], nodes[eb]
            print >> log, "merging nodes:", na.get_name(), nb.get_name()
            newnode = pydot.Node(na.get_name() + nb.get_name(), label=na.get_label()[:-1] + "\\n" + nb.get_label()[1:], shape="box")
            for k,n in nodes.iteritems():
                if "%X"%k in newnode.get_name(): nodes[k] = newnode

    edges = {}
    for cpf in CP:
        cp = cp_only(cpf)
        for i in range(1,len(cp)):
            ea = cp[i-1]
            eb = cp[i]
            if degi[ea] == 1 and dego[eb] == 1:
                continue
            if (ea,eb) not in edges:
                cond = string.join(cpf[i][1], ", ")
                edges[(ea,eb)] = pydot.Edge(nodes[ea], nodes[eb], label='"%s"' % cond, color=COLOR[(ea,eb)], weight=str(W[(ea,eb)]))
    # end merge nodes

    for k,ea in nodes.iteritems():
        print >> log, k, ea, ea.get_label()
        graph.add_node(ea)
        
    for k,ea in edges.iteritems():
        print >> log, ea,k
        graph.add_edge(ea)

    #~ print >> sys.stderr, "rendering"
    graph.write_svg(filename, prog='dot') 
    #~ print >> sys.stderr, "yay!"
    log.flush()
    clog.flush()


def print_cp(cp):
    print "" 
    print "CODE PATH:"
    for ea in cp:
        #~ print "%X"%ea, "   ", GetDisasmQ(ea)
        disasm.show_disasm(idapy._d, ea)



class ARMState:
    def __init__(self):
        self.reset()
        
    def reset(self, startFunc=False):

        self.SP = Symbol('unk_SP')
        self.LR = Symbol('unk_LR')
        self.R0 = Symbol('unk_R0')
        self.R1 = Symbol('unk_R1')
        self.R2 = Symbol('unk_R2')
        self.R3 = Symbol('unk_R3')
        self.R4 = Symbol('unk_R4')
        self.R5 = Symbol('unk_R5')
        self.R6 = Symbol('unk_R6')
        self.R7 = Symbol('unk_R7')
        self.R8 = Symbol('unk_R8')
        self.R9 = Symbol('unk_R9')
        self.R10 = Symbol('unk_R10')
        self.R11 = Symbol('unk_R11')
        self.R12 = Symbol('unk_R12')
        self.R13 = Symbol('unk_R13')
        self.R14 = self.LR
        #self.R15 = Symbol('ARM.R15')

        self.PC = Symbol('unk_PC')
        self.N = Symbol('unk_N')
        self.Z = Symbol('unk_Z')
        self.C = Symbol('unk_C')
        self.V = Symbol('unk_V')
        self.I = Symbol('unk_I')
        self.F = Symbol('unk_F')
        self.S1 = Symbol('unk_S1')
        self.S0 = Symbol('unk_S0')
        
        self.CPSR = Symbol('unk_CPSR')
        self.SPSR = Symbol('unk_SPSR')
        
        
        self.MEMDIC = {}
        self.condFlags = "" # for if's
        self.currentBranchFlags = []

        if startFunc:
            self.SP = Symbol('sp0')
            self.LR = Symbol('lr0')
            self.CPSR = Symbol('cpsr0')
            self.SPSR = Symbol('spsr0')
            self.R0 = Symbol('arg0')
            self.R1 = Symbol('arg1')
            self.R2 = Symbol('arg2')
            self.R3 = Symbol('arg3')
            self.MEMDIC[self.SP] = Symbol('arg4')
            self.MEMDIC[self.SP+4] = Symbol('arg5')
            self.MEMDIC[self.SP+8] = Symbol('arg6')
            self.MEMDIC[self.SP+12] = Symbol('arg7')
            self.MEMDIC[self.SP+16] = Symbol('arg8')

    
    def getR15(self):
        return sign(self.S0) + \
               sign(self.S1) * 2 + \
               self.PC * 4 + \
               sign(self.F) * (1<<26) + \
               sign(self.I) * (1<<27) + \
               sign(self.V) * (1<<28) + \
               sign(self.C) * (1<<29) + \
               sign(self.Z) * (1<<30) + \
               sign(self.N) * (1<<31)
               
    def setR15(self, value):
        self.S0 = sign(value & (1<<0))
        self.S1 = sign(value & (1<<1))
        self.F = sign(value & (1<<26))
        self.I = sign(value & (1<<27))
        self.V = sign(value & (1<<28))
        self.C = sign(value & (1<<29))
        self.Z = sign(value & (1<<30))
        self.N = sign(value & (1<<31))
        self.PC = (value & 0x03FFFFFC) >> 2
    R15 = property(getR15, setR15)

    def setFlags(self, result):
        self.condFlags = result
        print >> clog, "set flags: %s" % STR(result)
        AddIf()
        try: 
            result = int(result)
            self.Z = 1 if result == 0 else 0
            self.N = 1 if result < 0 else 0
        except:
            self.Z = Symbol('unk_Z')
            self.N = Symbol('unk_N')



global ARM
ARM = ARMState()

def resetArm(func=False):
    #~ print "Resetting ARM emulator: func =", func
    ARM.reset(func)
    global indent, condit
    indent = ""
    condit = ""

def mem(ea):
    #print >> log, "mem(%s)" % ea
    try:
        ea = int(ea)
        val = Byte(ea) + Byte(ea+1) * (1<<8) + Byte(ea+2) * (1<<16) + Byte(ea+3) * (1<<24)
        if val != 0xFFFFFFFF:
            return "0x%X" % val
    except:
        pass
    try:
        return "MEMREAD(0x%X)" % ea
    except:
        return "MEMREAD(%s)" % ea

def STOREMEM(addr, value):
    try: addr = copy(addr)
    except: pass
    try: value = copy(value)
    except: value = Symbol("whoops_" + str(value))
    
    try: addr = int(addr)
    except: pass
    ARM.MEMDIC[addr] = value # volatile memory (to be an option)
    print >> log, "  * stored:", STR(value)
    print >> clog, "*(%s) = %s" % (addr, STR(value))
    #~ if "sp0" not in str(addr):
    AddInstr(MEMWRITE(addr, value))

def ReadROM(ea):
    return idapy._d.ROM.get(ea)

# pointer dereference operator... or memory acces
# this one evaluates either to an abstract memory read (MEM) or to a concrete value/symbol
class MEMREAD(Function):
    @classmethod
    def eval(cls, ea):
        ea = copy(ea)
        #~ print ea
        if type(ea) == STRUCTPTR_MAYBE:
            return MEMREAD(STRUCTPTR(ea.args[0]))
        if type(ea) == Add:
            if type(ea.args[1]) == STRUCTPTR_MAYBE:
                assert len(ea.args) == 2
                return MEMREAD(Add(ea.args[0], STRUCTPTR(ea.args[1].args[0])))

        if ea in ARM.MEMDIC:
            return copy(ARM.MEMDIC[ea])
        try:
            ea = int(ea)
            return Uint32(ea)
        except:
            pass
        return MEM(ea)

class MEMWRITE(Function):
    @classmethod
    def eval(cls, ea, value):
        ea = copy(ea)
        #~ print ea
        if type(ea) == STRUCTPTR_MAYBE:
            return MEMWRITE(STRUCTPTR(ea.args[0]), value)
        if type(ea) == Add:
            if type(ea.args[1]) == STRUCTPTR_MAYBE:
                assert len(ea.args) == 2
                return MEMWRITE(Add(ea.args[0], STRUCTPTR(ea.args[1].args[0])), value)

# this one only reads from ROM upon evaluation
class MEM(Function):
    @classmethod
    def eval(cls, ea):
        ea = copy(ea)
        try:
            ea = int(ea)
            return Uint32(ea)
        except:
            pass

class LSL(Function): 
    
    @classmethod
    def eval(cls, a, b):
        try: 
            b = int(b)
            return a * (2**b)
        except: pass
        
    #~ def __str__(cls):
        #~ return "covrig"
        #~ a = cls.args[0]
        #~ b = cls.args[1]
        #~ return "(%s << %s)" % (a,b)

class ASL(Function): # same as LSL
    @classmethod
    def eval(cls, a, b):
        try: 
            b = int(b)
            return a * (2**b)
        except: pass
            

class LSR(Function):
    @classmethod
    def eval(cls, a, b):
        try: 
            b = int(b)
            return a / (2**b)
        except: pass

class ASR(Function):
    @classmethod
    def eval(cls, a, b):
        try: 
            b = int(b)
            return a / (2**b)
        except: pass

class BIC(Function): pass
class ROR(Function): pass
class ROL(Function): pass

# BYTE(BYTE(x)) = BYTE(x)
# BYTE(HALFWORD(x)) = BYTE(x)
class BYTE(Function):
    @classmethod
    def eval(cls, a):
        if type(a) in [BYTE]:
            return a
        if type(a) in [HALFWORD]:
            return BYTE(a.args[0])

# HALFWORD(BYTE(x)) = BYTE(x)
# HALFWORD(HALFWORD(x)) = HALFWORD(x)
class HALFWORD(Function):
    @classmethod
    def eval(cls, a):
        if type(a) in [BYTE, HALFWORD]:
            return a
class AND(Function):
    @classmethod
    def eval(cls, a, b):
        if b == 0xFF:
            return BYTE(a)
        if b == 0xFFFF:
            return HALFWORD(a)

class OR(Function):
    pass

class XOR(Function):
    pass

class STRUCT(Function):
    pass

class STRUCTPTR(Function):
    pass
    
class STRUCTPTR_MAYBE(Function): # could be unnamed struct or plain integer; if used in MEM(integer_off + struct_addr), it's considered a struct
    pass
    #~ @classmethod
    #~ def eval(cls, a):
        #~ print "STRUCTPTR_MAYBE eval to", a
        #~ return a


class infix:
    def __init__(self, function):
        self.function = function
    def __rmul__(self, other):
        return infix(lambda x, self=self, other=other: self.function(other, x))
    def __mul__(self, other):
        return self.function(other)

lsl = infix(lambda x,y: LSL(x,y))
lsr = infix(lambda x,y: LSR(x,y))
asl = infix(lambda x,y: LSL(x,y)) # ASL is the same as LSL
asr = infix(lambda x,y: ASR(x,y))
ror = infix(lambda x,y: ROR(x,y))
rol = infix(lambda x,y: ROL(x,y))
andop = infix(lambda x,y: AND(x,y))
orop = infix(lambda x,y: OR(x,y))
xor = infix(lambda x,y: XOR(x,y))
bic = infix(lambda x,y: BIC(x,y))
rsb = infix(lambda x,y: y-x)

def TranslatePhrase(s):
    if not s.strip(): return ""
    elements = s.split(",")
    enew = ["0"]
    for ea in elements:
        if re.match("(SP|LR|PC|R[0-9]+)", ea):
            enew.append("+ ARM." + ea)
        elif re.match("-(SP|LR|PC|R[0-9]+)", ea):
            enew.append("- ARM." + ea[1:])
        elif ea.startswith("#-"):
            enew.append("- " + ea[2:])
        elif ea.startswith("#"):
            enew.append("+ " + ea[1:])
        elif ea.startswith("LSL#"):                  # todo: fix this
            enew.append("*lsl* " + ea[4:])
        elif ea.startswith("LSR#"):
            enew.append("*lsr* " + ea[4:])
        elif ea.startswith("ASL#"):
            enew.append("*asl* " + ea[4:])
        elif ea.startswith("ASR#"):
            enew.append("*asr* " + ea[4:])
        elif ea.startswith("ROR#"):
            enew.append("*ror* " + ea[4:])
        elif ea.startswith("ROL#"):
            enew.append("*rol* " + ea[4:])

        elif ea.startswith("LSL "): 
            enew.append("*lsl* " + TranslatePhrase(ea[4:]))
        elif ea.startswith("LSR "):
            enew.append("*lsr* " + TranslatePhrase(ea[4:]))
        elif ea.startswith("ASL "):
            enew.append("*asl* " + TranslatePhrase(ea[4:]))
        elif ea.startswith("ASR "):
            enew.append("*asr* " + TranslatePhrase(ea[4:]))
        elif ea.startswith("ROR "):
            enew.append("*ror* " + TranslatePhrase(ea[4:]))
        elif ea.startswith("ROL "):
            enew.append("*rol* " + TranslatePhrase(ea[4:]))
        else:
            raise Exception, "unhandled phrase: " + s
    #~ print >> log, enew
    return str(string.join(enew))
    
#~ print >> log, TranslatePhrase("R1,R2")
#~ print >> log, TranslatePhrase("R1,R2,#3")
#~ print >> log, TranslatePhrase("R1,R2,#-0x3f")
#~ print >> log, TranslatePhrase("R1,-R2,LSL#3")

def ParseRegList(exp):
    assert exp.startswith("{") and exp.endswith("}")
    exp = exp[1:-1]
    grps = exp.split(",")
    regs = []
    for g in grps:
        m = re.match("R([0-9]+)-R([0-9]+)", g)
        if m:
            a,b = m.groups()[0:2]
            for i in range(int(a),int(b)+1):
                regs.append("R%d" % i)
        else:
            regs.append(g)
    return regs

def TranslatePostindex(grps):
    inside = grps[0]
    outside = grps[1]
    dest = "ARM." + GetFirstWordD(inside)
    if outside.startswith(","):
        incr = TranslatePhrase(outside[1:])
        if incr:
            return dest + " += " + incr
    elif outside.startswith("!"):
        assert(outside == "!")
        return dest + " = " + TranslatePhrase(inside)
    
def TranslateOperand(ea,i,lhs=False,dest=False):
    t = GetOpType(ea,i)
    if t == o_reg:
        if GetOperandValue(ea,i) == 15:
            if dest:
                return ("ARM.R15" if GetFlagSuffix(ea) else "ARM.PC"), None
            else:
                return ("ARM.PC" if lhs else "ARM.PC"), None
        else:
            return "ARM." + GetOpnd(ea,i), None
    elif t == o_imm:
        return str(GetOperandValue(ea,i)), None
    elif t in [o_mem, o_far, o_near]:
        return MEMREAD(GetOperandValue(ea,i)), None
        
    elif t in [o_phrase, o_displ]:
        OpSeg(ea,i)
        m = re.match("\[(.*)\](.*)", GetOpnd(ea,i).strip())
        addr = TranslatePhrase(m.groups()[0])
        post = TranslatePostindex(m.groups())
        #print >> log, "addr:", eval(addr), type(eval(addr))
        return (addr if dest else "MEMREAD(" + str(addr) + ")"), post
    elif t == 8: # MOV R2, R1, LSR#24
        return TranslatePhrase(GetOpnd(ea,i)), None
    elif t == None:
        return None, None
    raise Exception, "operand %d not handled: %s (type=%d)" % (i,GetDisasmQ(ea), t)

def getRegsS(op):
    R = []
    regs = re.split("(R[0-9]+)[^0-9]", str(op) + " ")
    for r in regs:
        if len(r) == 2 and r[0] == "R":
            R.append(r)
    return R

def STR(x, pointsto=False):
    try:
        x = int(x)
        
        fn = GetFunctionName(x)
        fo = GetFuncOffset(x)
        if fn == fo: return "@" + fn
        
        if x > 0x500 and x in idapy._d.A2N:
            return idapy._d.A2N[x]
        
        s = GetString(x)
        x0 = x
        x = ctypes.c_uint32(x).value
        if s: 
            rs = repr(s).replace("|", "!")
            return '%s' % (rs)
            return '/*%s*/ %s' % (hex(x), rs)
        #~ if abs(x0) < 10: return "%d" % x0                # for small numbers, return the decimal
        #if len(list("%d" % x).replace(0,"")) >= 3: return  "0x%X" % x  # if in decimal is a "dirty" number, return the hex
        #if len(list("%X" % x).replace(0,"")) == 1: return  "0x%X" % x # if it's a clean number in hex, like 0x100, 0x1000, 0x3000..
        plushex = "0x" + hex(x)
        minushex = ("0x%X" % ctypes.c_int32(x).value).replace("0x-", "-0x")
        plusdec = str(ctypes.c_uint32(x).value)
        minusdec = str(ctypes.c_int32(x).value)
        candidates = [plusdec, plushex, minusdec, minushex]
        #~ print candidates
        cost = [0.5 * len(x) # short is better
                + len(set(x)) # few unique digits is better
                - (0.5 if "0" in x.replace("0x","") else 0) # prefer numbers with zeros
                - (0.5 if x[-1] == "0" else 0) # prefer numbers ending in 0
                + (0.5 if x[0] == "-" and len(x) > 3 else 0) # penalty for negative numbers
                - (3 if x.startswith("0xFF") and not x.startswith("0xFFFFF") else 0)  # this may be an address in ROM => prefer hex
                for x in candidates]
        #~ print cost
        for c,p in zip(candidates,cost):
            if p == min(cost):
                return c
    except:
        comment = ""
        if pointsto and x in ARM.MEMDIC:
            try:
                comment = " /* points to %s */ " % STR(ARM.MEMDIC[x])
            except:
                comment = " /* points to %s */ " % str(ARM.MEMDIC[x])
        return "%s%s" % (str(x), comment)

def print_stack():
    for k in range(100):
        if ARM.SP+k*4 in ARM.MEMDIC:
            val = MEMREAD(ARM.SP+k*4)
            if val:
                print >> log, "  * SP+0x%02x => %s" % (k*4, val)


def GetFirstWordD(s):
    s = re.match("([A-Z0-9]*)", s).groups()[0]
    return s

def run(code):
    print >> log, "  =>", code
    exec(code)
    
    #~ print >> log, "  R0 = ", ARM.R0
    #~ print >> log, "  R1 = ", ARM.R1
    #~ print >> log, "  R2 = ", ARM.R2
    #~ print >> log, "  R3 = ", ARM.R3


def emusym_code_path(cpf, codetree=False):
    
    if codetree:
        global CTree, CurrPos
        CTree = []
        CurrPos = CTree
    
    if not cpf: return
    cp,cf = split_code_path_ea_cond(cpf)
    print >> log, ""
    print >> log, "*******************************************"
    print >> log, "emulating from 0x%X: %s" % (cp[0], GetDisasmQ(cp[0]))
    print >> log, "*******************************************"

    print >> clog, ""
    print >> clog, "*******************************************"
    print >> clog, "emulating from 0x%X: %s" % (cp[0], GetDisasmQ(cp[0]))
    print >> clog, "*******************************************"
    unhandled = 0
    #~ print cpf
    lr_stored = 0
    for kcpf,elem in enumerate(cpf):
        clear_cache()
        jumptable_offset = None
        if type(elem) == tuple:  # code path with branch info
            ea,f = elem
            ARM.currentBranchFlags = f
            try: next_ea = cpf[kcpf+1][0]
            except: next_ea = ea;
        else:                    # plain, simple code path (only addresses)
            ea = elem
            try: next_ea = cpf[kcpf+1]
            except: next_ea = ea;
            
        print >> log, GetDisasmQ(ea)
        
        ARM.PC = ea+8

        mne = GetMnem(ea)
        msf = GetModeSuffix(ea)
        if lr_stored: lr_stored -= 1
        if mne in ["MOV", "LDR", "MRS", "MSR", "MVN"]:
            if mne == "MOV" and GetOpnds(ea) == "LR, PC":
                lr_stored = 2
                continue
                
            t0 = GetOpType(ea,0);
            a,post = TranslateOperand(ea, 0, dest=True)
            #~ print >> log, "a = ", a
            b,post = TranslateOperand(ea, 1)
            #~ print >> log, "b = ", b
            if mne == "MVN": b = "-(%s)-1" % b
            
            if mne == "MSR":
                ARM.CPSR = Symbol("cpsr_%x" % ea)
            
            if 'ARM.PC' in b and 'MEM' in b: # PC-relative indirect addressing: maybe a struct?
                try:
                    if eval(b) not in idapy._d.ROM and eval(b) > 0x1000 and eval(b) < 0x100000:
                        if eval(b) in idapy._d.A2N:
                            if not idapy._d.A2N[eval(b)].isupper(): # uppercase names are not structs
                                b = "STRUCTPTR(%s)" % eval(b)
                        else:
                            if guess_unknown_structs:
                                b = "STRUCTPTR_MAYBE(%s, evaluate=False)" % eval(b)
                                # don't evaluate this right now
                                # we'll find out if it's a struct if it will become an argument of some MEMREAD/MEMWRITE
                                # otherwise, it's a plain number, and it will be evaluated (and simplified) at rebuilding stage
                except: pass
            
            B,H = GetByteSuffix(ea), GetHalfwordSuffix(ea)
            if B or H:
                run("%s = (%s) *andop* 0x%X" % (a, b, BHMask[B+H]))
            else:
                run("%s = %s" % (a, b))
            if not a.startswith("ARM.R"):
                if codetree: AddInstr(REGWRITE(a[4:], eval(a)))
            if GetFlagSuffix(ea):
                run("ARM.setFlags(" + a + ")")
            if post: run(post)
            print >> log, "  * %s = %s" % (a, STR(eval(a)))

        elif mne == "ADR":
            a,post = TranslateOperand(ea, 0, dest=True)
            b,post = TranslateOperand(ea, 1)
            run(a + " = " + b)
            if GetFlagSuffix(ea):
                run("ARM.setFlags(" + a + ")")
            if post: run(post)
            print >> log, "  * %s = %s" % (a, STR(eval(a)))

        elif mne in ["ADD", "SUB", "RSB", "MUL", "AND", "ORR", "EOR", "BIC", "LSL", "LSR", "ASL", "ASR"]:
            a,post = TranslateOperand(ea, 0, dest=True)
            b,post = TranslateOperand(ea, 1, lhs=True)
            c,post = TranslateOperand(ea, 2)
            run(a + " = (" + b + ") " + Operands[mne] + " (" + c + ")")

            if codetree: 
                if not a.startswith("ARM.R") and not a.startswith("ARM.SP"):
                    AddInstr(REGWRITE(a[4:], eval(a)))

            if GetFlagSuffix(ea):
                run("ARM.setFlags(" + a + ")")
            if post: run(post)
            print >> log, "  * %s = %s" % (a, STR(eval(a)))
            
            if a == "ARM.PC":
                print "jump table?"
                if codetree: 
                    if b == "ARM.PC":
                        jumptable_offset = (next_ea - ea - 8) / 4;
                        print "jump table! var=%s off=%s" % (eval(c), jumptable_offset)
                        run("ARM.setFlags((" + c + ") / 4)")
                    else:
                        AddInstr(Symbol("! Changed PC register"))
                        break

        elif mne in ["MLA", "MLS"]:
            a,post = TranslateOperand(ea, 0, dest=True)
            b,post = TranslateOperand(ea, 1, lhs=True)
            c,post = TranslateOperand(ea, 2)
            d,post = TranslateOperand(ea, 3)
    
            add_or_sub = "+" if mne == "MLA" else "-"
            run(a + " = (" + b + ") * (" + c + ")" + add_or_sub + "(" + d + ")")

            if codetree: 
                if not a.startswith("ARM.R") and not a.startswith("ARM.SP"):
                    AddInstr(REGWRITE(a[4:], eval(a)))

            if GetFlagSuffix(ea):
                run("ARM.setFlags(" + a + ")")
            if post: run(post)
            print >> log, "  * %s = %s" % (a, STR(eval(a)))

        elif mne in ["CMP", "CMN", "TST", "TEQ"]:
            a,post = TranslateOperand(ea, 0, lhs=True)
            b,post = TranslateOperand(ea, 1)
            run("ARM.setFlags((" + a + ") " + Operands[mne] + " (" + b + "))")
            if post: run(post)
            
        elif mne == "STR":
            a,post = TranslateOperand(ea, 0)
            #~ print >> log, "a:", a
            b,post = TranslateOperand(ea, 1, dest=True)
            #~ print >> log, "b:", b
            B,H = GetByteSuffix(ea), GetHalfwordSuffix(ea)
            if B or H:
                run("STOREMEM(%s, (%s) *andop* 0x%X)" % (b, a, BHMask[B+H]))
            else:
                run("STOREMEM(%s, %s)" % (b, a))
            if post: run(post)
        # from http://www.heyrick.co.uk/assembler/str.html
        # FD = Pre-decremental store   (=DB)
        # FA = Pre-incremental store   (=IB)
        # ED = Post-dec                (=DA)
        # EA = Post-inc                (=IA)
        # default: EA=IA? http://www.keil.com/support/man/docs/armasm/armasm_cjagjjbc.htm
        elif mne == "STM" and msf in ["FD", "FA", "ED", "EA", "DB", "IB", "DA", "IA", None]:
            sign = "-" if msf in ["FD", "ED", "DB", "DA"] else "+"
            pre = 1 if msf in ["FD", "FA", "DB", "IB"] else 0
            rev = (msf in ["FD", "ED", "DB", "DA"])
            op0 = GetOpnd(ea,0)
            try: dest = getRegsS(op0)[0]
            except: dest = GetFirstWordD(op0)
            regs = ParseRegList(GetOpnd(ea,1))
            if rev:
                regs.reverse()
            for k,r in enumerate(regs):
                run("STOREMEM(ARM.%s %s %d, ARM.%s)" % (dest, sign, (k+pre)*4, r))
            if "!" in GetOpnd(ea,0):
                run("ARM.%s %s= %d" % (dest, sign, len(regs)*4))
        elif mne == "PUSH":
            regs = ParseRegList(GetOpnd(ea,0))
            regs.reverse()
            for k,r in enumerate(regs):
                run("STOREMEM(ARM.SP - %d, ARM.%s)" % ((k+1)*4, r))
            run("ARM.SP -= %d" % (len(regs)*4))
        elif mne == "POP":
            regs = ParseRegList(GetOpnd(ea,0))
            regs.reverse()
            for k,r in enumerate(regs):
                run("ARM.%s = MEMREAD(ARM.SP + %d)" % (r, (k)*4))
            for k,r in enumerate(regs):
                print >> log, "  * ARM.%s = %s" % (r, eval("ARM.%s" % r))
            run("ARM.SP += %d" % (len(regs)*4))
            print >> log, "  * ARM.SP = %s" % ARM.SP
            
            #~ print_stack()

        # EA = Pre-decremental load   (=DB)
        # ED = Pre-incremental load   (=IB)
        # FA = Post-dec               (=DA)
        # FD = Post-inc               (=IA)
        elif mne == "LDM" and msf in ["FD", "FA", "ED", "EA", "DB", "IB", "DA", "IA", None]:
            sign = "-" if msf in ["EA", "FA", "DB", "DA"] else "+"
            pre = 1 if msf in ["EA", "ED", "DB", "IB"] else 0
            rev = (msf not in ["EA", "FA", "DB", "DA"])
            op0 = GetOpnd(ea,0)
            try: src = getRegsS(op0)[0]
            except: src = GetFirstWordD(op0)
            regs = ParseRegList(GetOpnd(ea,1))
            if rev:
                regs.reverse()
            for k,r in enumerate(regs):
                run("ARM.%s = MEMREAD(ARM.%s %s %d)" % (r, src, sign, (k+pre)*4))
            for k,r in enumerate(regs):
                print >> log, "  * ARM.%s = %s" % (r, eval("ARM.%s" % r))
                
            if "!" in GetOpnd(ea,0):
                run("ARM.%s %s= %d" % (src, sign, len(regs)*4))
                print >> log, "  * ARM.%s = %s" % (src, eval("ARM.%s" % src))


        elif mne == "MCR":
            print >> log, "write to coprocessor:", GetDisasmQ(ea)
            for r in getRegsS(GetDisasmQ(ea).split(";")[0]):
                print >> log, "  * ARM.%s = %s" % (r, eval("ARM.%s" % r))
        elif mne == "MRC":
            print >> log, "read from coprocessor:", GetDisasmQ(ea)
            for r in getRegsS(GetDisasmQ(ea).split(";")[0]):
                run("ARM.%s = Symbol('cop_%X')" % (r, ea))

        elif mne == "B":
            if lr_stored:
                print "CALL?!?!", GetDisasmQ(ea)
            if ea != cp[-1]:
                print >> log, "  => ignoring (was handled by code path extractor)"
            else:
                print >> log, "" 
                print >> log, "TAIL CALL:", GetOpnd(ea,0)
                dest,post = TranslateOperand(ea,0)
                func = eval(dest)
                
                args = [ARM.R0, ARM.R1, ARM.R2, ARM.R3] + [ ARM.MEMDIC.get(ARM.SP+k, MEMREAD(ARM.SP+k)) for k in range(0,13,4)]
                if dest.startswith("ARM.R"):
                    args = args[:GetOperandValue(ea,0)]
                if codetree:
                    #~ print MEMREAD(ARM.SP)
                    #~ print ARM.MEMDIC
                    #~ print copy(ARM.SP) in ARM.MEMDIC, ARM.MEMDIC.get(ARM.SP)
                    #~ print str(CALL(ea, func, *args))
                    try: AddInstr(CALL(ea, func, *args))
                    except: 
                        AddInstr(Symbol("Buggy_CALL"))
                        raise
                if isAbortFunc(func): break
                run("ARM.R0 = Symbol('%s')" % RetName(func, ea))
    

        elif IsReturn(ea):
            pass # will be handled later
            
        elif mne == "BL":
            print >> log, "" 
            print >> log, "CALL:", GetOpnd(ea,0)
            #~ print >> log, "R0 = ", STR(ARM.R0)
            #~ print >> log, "R1 = ", STR(ARM.R1)
            #~ print >> log, "R2 = ", STR(ARM.R2)
            #~ print >> log, "R3 = ", STR(ARM.R3)
            #~ print >> log, "SP = ", STR(ARM.SP)
            #~ print >> clog, "ret_%s_%s = %s(%s, %s, %s, %s)" % (GetOpnd(ea,0), "%X"%ea, GetOpnd(ea,0), STR(ARM.R0), STR(ARM.R1), STR(ARM.R2), STR(ARM.R3))

            dest,post = TranslateOperand(ea,0)
            func = eval(dest)
            
            args = [ARM.R0, ARM.R1, ARM.R2, ARM.R3] + [ ARM.MEMDIC.get(ARM.SP+k, MEMREAD(ARM.SP+k)) for k in range(0,13,4)]
            if dest.startswith("ARM.R"):
                args = args[:GetOperandValue(ea,0)]
            if codetree:
                #~ print MEMREAD(ARM.SP)
                #~ print ARM.MEMDIC
                #~ print copy(ARM.SP) in ARM.MEMDIC, ARM.MEMDIC.get(ARM.SP)
                #~ print str(CALL(ea, func, *args))
                #~ try: AddInstr(Symbol(str(CALL(ea, func, *args))))
                try: AddInstr(CALL(ea, func, *args))
                except: 
                    AddInstr(Symbol("Buggy_CALL"))
                    raise
            if isAbortFunc(func): break
            run("ARM.R0 = Symbol('%s')" % RetName(func, ea))

        elif mne == "BLX":
            dest,post = TranslateOperand(ea,0)
            func = eval(dest)            
            if codetree: 
                print >> log, CALL(ea, func, ARM.R0, ARM.R1, ARM.R2, ARM.R3, MEMREAD(ARM.SP), MEMREAD(ARM.SP+4), MEMREAD(ARM.SP+8), MEMREAD(ARM.SP+12))
                try: AddInstr(CALL(ea, func, ARM.R0, ARM.R1, ARM.R2, ARM.R3, MEMREAD(ARM.SP), MEMREAD(ARM.SP+4), MEMREAD(ARM.SP+8), MEMREAD(ARM.SP+12)))
                except: 
                    AddInstr(Symbol("Buggy_CALL"))
                    raise

            if isAbortFunc(func): break
            run("ARM.R0 = Symbol('ret_%s_%s')" % (func, "%X"%ea))

        elif mne == "BX":
            if lr_stored:
                dest,post = TranslateOperand(ea,0)
                func = eval(dest)
                args = [ARM.R0, ARM.R1, ARM.R2, ARM.R3] + [ MEMREAD(ARM.SP+k) for k in range(0,13,4)]
                if dest.startswith("ARM.R"):
                    args = args[:GetOperandValue(ea,0)]
                if codetree:
                    #~ print MEMREAD(ARM.SP)
                    #~ print ARM.MEMDIC
                    #~ print copy(ARM.SP) in ARM.MEMDIC, ARM.MEMDIC.get(ARM.SP)
                    print >> log, str(CALL(ea, func, *args))
                    #~ try: AddInstr(Symbol(str(CALL(ea, func, *args))))
                    try: AddInstr(CALL(ea, func, *args))
                    except: 
                        AddInstr(Symbol("Buggy_CALL"))
                        raise

                if isAbortFunc(func): break
                run("ARM.R0 = Symbol('%s')" % RetName(func, ea))

            else:
                dest,post = TranslateOperand(ea,0)
                if codetree: AddInstr(JUMP(eval(dest)))
                break

        else:
            print >> log, "unhandled:", GetDisasmQ(ea)
            for r in getRegsS(GetDisasmQ(ea).split(";")[0]):
                run("ARM." + r + " = Symbol('unhandled." + r + "')")
            unhandled += 1
            if codetree: AddInstr(Symbol("Unhandled_" + str(GetMnem(ea))))

        if IsReturn(ea):
            print >> log, "  => return"
            if ea != cp[-1]: print "WARNING: return is not at the end of the code path"
            print >> clog, "return ", STR(ARM.R0)
            if codetree: AddInstr(RETURN(ARM.R0))
            break

    print >> log, "END OF CODE PATH"
    print >> log, "R0 = ", STR(ARM.R0)
    print >> log, "R1 = ", STR(ARM.R1)
    print >> log, "R2 = ", STR(ARM.R2)
    print >> log, "R3 = ", STR(ARM.R3)
    print >> log, "SP = ", STR(ARM.SP)
    if STR(ARM.SP) != "sp0":
        if codetree: AddInstr(Symbol("!!! Stack not restored !!!"))
    #pprint(ARM.MEMDIC)
    if codetree: AddInstr(Symbol("!end"))

    print >> clog, "END OF CODE PATH"
    print >> clog, "R0 = ", STR(ARM.R0)

    print >> log, "unhandled instructions: %d" % unhandled
    #sys.stdout.close()

    log.flush()
    clog.flush()
    
    if codetree:
        #~ print CTree
        st = make_symbolic_tree(CTree)
        #~ print st
        return copy(st)
