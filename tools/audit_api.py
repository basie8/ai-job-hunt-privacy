#!/usr/bin/env python3
"""Verify every MQL5 built-in call against its documented signature."""
import re,glob,sys

# name -> (min_args, max_args, note)
SIG={
 'iMA':(6,6,'symbol,tf,period,shift,method,price'),
 'iRSI':(4,4,'symbol,tf,period,price'),
 'iMACD':(6,6,'symbol,tf,fast,slow,signal,price'),
 'iADX':(3,3,'symbol,tf,period'),
 'iStochastic':(7,7,'symbol,tf,K,D,slowing,method,field'),
 'iBands':(6,6,'symbol,tf,period,shift,deviation,price'),
 'iATR':(3,3,'symbol,tf,period'),
 'iHigh':(3,3,'symbol,tf,shift'),'iLow':(3,3,'symbol,tf,shift'),
 'iOpen':(3,3,'symbol,tf,shift'),'iClose':(3,3,'symbol,tf,shift'),
 'iTime':(3,3,'symbol,tf,shift'),
 'CopyBuffer':(5,5,'handle,buffer,start,count,array'),
 'CopyRates':(5,5,'symbol,tf,start,stop|count,array'),
 'CopyHigh':(5,5,'symbol,tf,start,count,array'),
 'CopyLow':(5,5,'symbol,tf,start,count,array'),
 'CopyTickVolume':(5,5,'symbol,tf,start,count,array'),
 'WebRequest':(7,9,'method,url,headers,timeout,data,result,result_headers'),
 'CalendarValueHistory':(3,5,'values,from,to[,country][,currency]'),
 'CalendarEventById':(2,2,'event_id,event'),
 'CalendarCountryById':(2,2,'country_id,country'),
 'OrderCalcMargin':(5,5,'type,symbol,volume,price,&margin'),
 'HistorySelect':(2,2,'from,to'),
 'HistoryDealGetTicket':(1,1,'index'),
 'HistoryDealSelect':(1,1,'ticket'),
 'HistoryDealGetDouble':(2,2,'ticket,prop'),
 'HistoryDealGetInteger':(2,2,'ticket,prop'),
 'HistoryDealGetString':(2,2,'ticket,prop'),
 'PositionSelectByTicket':(1,1,'ticket'),
 'SymbolInfoDouble':(2,3,'symbol,prop[,&val]'),
 'SymbolInfoInteger':(2,3,'symbol,prop[,&val]'),
 'SymbolSelect':(2,2,'symbol,enable'),
 'ObjectCreate':(6,7,'chart,name,type,subwin,time,price[,...]'),
 'ObjectSetInteger':(4,5,'chart,name,prop[,modifier],value'),
 'ObjectSetString':(4,5,'chart,name,prop[,modifier],value'),
 'ObjectGetInteger':(3,5,'chart,name,prop'),
 'ObjectFind':(2,2,'chart,name'),
 'ObjectDelete':(2,2,'chart,name'),
 'ObjectsDeleteAll':(2,4,'chart,prefix[,subwin][,type]'),
 'StringSplit':(3,3,'string,sep,array'),
 'StringSubstr':(2,3,'string,start[,count]'),
 'StringFind':(2,3,'string,substr[,start]'),
 'StringGetCharacter':(2,2,'string,pos'),
 'StringReplace':(3,3,'string,find,replace'),
 'ArrayMinimum':(1,3,'array[,start][,count]'),
 'ArrayMaximum':(1,3,'array[,start][,count]'),
 'ArrayResize':(2,3,'array,size[,reserve]'),
 'ArraySetAsSeries':(2,2,'array,flag'),
 'StructToTime':(1,1,'MqlDateTime'),
 'TimeToStruct':(2,2,'datetime,&struct'),
 'CharArrayToString':(1,4,'array[,start][,count][,codepage]'),
 'FileOpen':(2,4,'name,flags[,delim][,codepage]'),
 'FileIsExist':(1,2,'name[,common]'),
 'EventSetTimer':(1,1,'seconds'),
 'ChartRedraw':(0,1,'[chart]'),
 'MathRound':(1,1,'x'),'MathAbs':(1,1,'x'),'MathPow':(2,2,'base,exp'),
 'MathMin':(2,2,'a,b'),'MathMax':(2,2,'a,b'),'MathFloor':(1,1,'x'),
 'NormalizeDouble':(2,2,'value,digits'),
 'MQLInfoInteger':(1,1,'prop'),
 'IndicatorRelease':(1,1,'handle'),
}

def split_args(s):
    """split a call's argument list at top-level commas"""
    out=[];depth=0;cur='';i=0
    while i<len(s):
        c=s[i]
        if c in '([{': depth+=1
        elif c in ')]}': depth-=1
        if c=='"':
            cur+=c;i+=1
            while i<len(s) and s[i]!='"':
                cur+=s[i]; i+= 2 if s[i]=='\\' else 1
            cur+=s[i] if i<len(s) else ''
            i+=1; continue
        if c=="'":
            cur+=c;i+=1
            while i<len(s) and s[i]!="'":
                cur+=s[i]; i+= 2 if s[i]=='\\' else 1
            cur+=s[i] if i<len(s) else ''
            i+=1; continue
        if c==',' and depth==0:
            out.append(cur.strip());cur='';i+=1;continue
        cur+=c;i+=1
    if cur.strip() or out: out.append(cur.strip())
    return [a for a in out if a!='']

bad=0;checked=0
for f in sorted(glob.glob('MQL5/Experts/XAUUSD_FTMO/**/*.mq*',recursive=True)):
    src=open(f).read()
    # drop comments
    src=re.sub(r'//[^\n]*','',src)
    for name,(lo,hi,note) in SIG.items():
        for m in re.finditer(r'(?<![\w.])'+name+r'\s*\(',src):
            start=m.end();depth=1;i=start
            while i<len(src) and depth>0:
                if src[i]=='"':
                    i+=1
                    while i<len(src) and src[i]!='"': i+= 2 if src[i]=='\\' else 1
                elif src[i]=="'":
                    i+=1
                    while i<len(src) and src[i]!="'": i+= 2 if src[i]=='\\' else 1
                elif src[i]=='(': depth+=1
                elif src[i]==')': depth-=1
                i+=1
            inner=src[start:i-1]
            args=split_args(inner)
            checked+=1
            if not (lo<=len(args)<=hi):
                line=src[:m.start()].count('\n')+1
                print(f"  ARG COUNT  {f}:{line}  {name}() got {len(args)}, expected {lo}..{hi}  [{note}]")
                print(f"             -> {inner[:110]}")
                bad+=1
print(f"\nchecked {checked} built-in calls across {len(SIG)} distinct API functions")
print("API SIGNATURES:", "PASS" if bad==0 else f"{bad} MISMATCH(ES)")
sys.exit(1 if bad else 0)
