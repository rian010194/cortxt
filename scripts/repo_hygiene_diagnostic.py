#!/usr/bin/env python3
"""Strictly read-only, fail-closed repository hygiene inventory."""
from __future__ import annotations
import argparse,json,subprocess,sys
from datetime import datetime,timezone,timedelta
from pathlib import Path

class DiagnosticError(RuntimeError): pass
def run(cmd,repo,runner=subprocess.run,ok=(0,)):
 try:p=runner(cmd,cwd=str(repo),capture_output=True,text=True,timeout=30)
 except (OSError,TimeoutError,subprocess.TimeoutExpired) as e: raise DiagnosticError(f"unavailable: {' '.join(cmd)}") from e
 if p.returncode not in ok: raise DiagnosticError(f"{' '.join(cmd)} failed: {p.stderr.strip()}")
 return p
def primary(repo,runner):
 p=Path(run(["git","rev-parse","--path-format=absolute","--git-common-dir"],repo,runner).stdout.strip())
 return p.parent if p.name==".git" else repo.resolve()
def worktrees(repo,runner):
 text=run(["git","worktree","list","--porcelain"],repo,runner).stdout; rows=[]
 for block in text.strip().split("\n\n") if text.strip() else []:
  x={"branch":None,"detached":False,"prunable":False}
  for line in block.splitlines():
   if line.startswith("worktree "):x["path"]=line[9:]
   elif line.startswith("HEAD "):x["head"]=line[5:]
   elif line.startswith("branch refs/heads/"):x["branch"]=line[18:]
   elif line=="detached":x["detached"]=True
   elif line.startswith("prunable"):x["prunable"]=True;x["prunable_reason"]=line[8:].strip()
  if "path" not in x:raise DiagnosticError("malformed worktree inventory")
  q=Path(x["path"]);x["exists"]=q.exists();x["dirty"]=bool(run(["git","status","--porcelain"],q,runner).stdout.strip()) if q.exists() else None;rows.append(x)
 return rows
def remote_base(repo,runner):
 ref=run(["git","symbolic-ref","refs/remotes/origin/HEAD"],repo,runner).stdout.strip()
 if not ref.startswith("refs/remotes/origin/"):raise DiagnosticError("malformed origin/HEAD")
 return ref
def prs(repo,runner):
 try:data=json.loads(run(["gh","pr","list","--state","open","--json","headRefName","--limit","500"],repo,runner).stdout)
 except ValueError as e:raise DiagnosticError("malformed PR inventory") from e
 if not isinstance(data,list):raise DiagnosticError("malformed PR inventory")
 return {x["headRefName"] for x in data if isinstance(x,dict) and x.get("headRefName")}
def branches(repo,runner,bound,heads,base):
 fmt="%(refname:short)%00%(objectname)%00%(committerdate:iso8601)%00%(upstream:short)%00%(upstream:track)"
 text=run(["git","for-each-ref",f"--format={fmt}","refs/heads/"],repo,runner).stdout;out=[];now=datetime.now(timezone.utc)
 for line in text.splitlines():
  p=line.split("\0")
  if len(p)!=5:raise DiagnosticError("malformed branch inventory")
  name,head,date,up,track=p;dt=datetime.fromisoformat(date).astimezone(timezone.utc);m=run(["git","merge-base","--is-ancestor",name,base],repo,runner,ok=(0,1));ahead=behind=None;upstream_gone="gone" in track
  if up and not upstream_gone:
   c=run(["git","rev-list","--left-right","--count",f"{name}...{up}"],repo,runner).stdout.split()
   if len(c)!=2:raise DiagnosticError("malformed ahead/behind inventory")
   ahead,behind=map(int,c)
  cat="protected" if name in {"main","master","trunk"} else "active-open-pr" if name in heads else "merged-candidate" if m.returncode==0 else "aged-no-pr" if now-dt>timedelta(days=30) else "no-pr"
  out.append({"name":name,"head":head,"upstream":up or None,"upstream_gone":upstream_gone,"ahead":ahead,"behind":behind,"worktree_bound":name in bound,"open_pr":name in heads,"merged_into":base if m.returncode==0 else None,"category":cat,"committer_date":date})
 return out
def stashes(repo,runner):
 text=run(["git","stash","list","--format=%gd%x00%ci%x00%gs"],repo,runner).stdout;out=[]
 for line in text.splitlines():
  p=line.split("\0",2)
  if len(p)!=3:raise DiagnosticError("malformed stash metadata")
  out.append(dict(zip(("ref","date","subject"),p)))
 return out
def store(path,kind):
 if path is None:return {"kind":kind,"status":"not_configured"}
 if kind=="daemon_claims" and path.is_dir():path=path/"claimed.json"
 if not path.exists():return {"kind":kind,"status":"absent","path":str(path)}
 if kind=="lifecycle" and path.is_dir():
  records=[]
  try:files=sorted(path.glob("session_*/session.json"))
  except OSError as e:raise DiagnosticError(f"{kind} unreadable: {e}") from e
  for item in files:
   try:json.loads(item.read_text(encoding="utf-8"))
   except (OSError,ValueError) as e:raise DiagnosticError(f"{kind} unreadable: {e}") from e
   records.append(str(item.parent.name))
  return {"kind":kind,"status":"ok","path":str(path),"record_count":len(records),"sessions":records}
 try:d=json.loads(path.read_text(encoding="utf-8"))
 except (OSError,ValueError) as e:raise DiagnosticError(f"{kind} unreadable: {e}") from e
 return {"kind":kind,"status":"ok","path":str(path),"record_count":len(d) if isinstance(d,(list,dict)) else 1}
REQ={"from","to","type","created","artifact","affects"}
def inbox(root):
 if root is None:return {"status":"not_configured"}
 if not root.exists():return {"status":"absent","path":str(root)}
 out=[]
 for p in sorted(root.glob("*/in/*.md")):
  text=p.read_text(encoding="utf-8");f={};lines=text.splitlines()
  if lines and lines[0]=="---" and "---" in lines[1:]:
   for line in lines[1:lines[1:].index("---")+1]:
    if ":" in line:k,v=line.split(":",1);f[k.strip()]=v.strip()
  a=f.get("artifact");artifact_exists=bool(a and ((root.parent.parent/a).exists() or (root.parent/a).exists()));out.append({"path":str(p),"missing_fields":sorted(REQ-set(f)),"valid_type":f.get("type") in {"delivery","request","handoff"},"artifact":a,"artifact_exists":artifact_exists})
 return {"status":"ok","path":str(root),"backlog":len(out),"messages":out}
def diagnose(repo,runner=subprocess.run,daemon_claims=None,lifecycle_store=None,inbox_root=None):
 repo=repo.resolve();home=primary(repo,runner);w=worktrees(repo,runner);base=remote_base(repo,runner);h=prs(repo,runner);b=branches(repo,runner,{x["branch"] for x in w if x["branch"]},h,base);s=stashes(repo,runner);root=home.parent/f"{home.name}-worktrees"
 for x in w:x["under_canonical_root"]=Path(x["path"]).is_relative_to(root)
 return {"status":"complete","timestamp":datetime.now(timezone.utc).isoformat(),"repo":str(repo),"primary_repo":str(home),"canonical_worktree_root":str(root),"remote_base":base,"worktrees":w,"branches":b,"stashes":s,"daemon_claims":store(daemon_claims,"daemon_claims"),"lifecycle_store":store(lifecycle_store,"lifecycle"),"inbox":inbox(inbox_root),"summary":{"total_worktrees":len(w),"dirty_worktrees":sum(x["dirty"] is True for x in w),"prunable_worktrees":sum(x["prunable"] for x in w),"detached_worktrees":sum(x["detached"] for x in w),"total_branches":len(b),"stash_count":len(s)}}
def main(argv=None):
 p=argparse.ArgumentParser();p.add_argument("--repo",type=Path,default=Path.cwd());p.add_argument("--json",action="store_true");p.add_argument("--daemon-claims",type=Path);p.add_argument("--lifecycle-store",type=Path);p.add_argument("--inbox-root",type=Path);a=p.parse_args(argv)
 try:r=diagnose(a.repo,daemon_claims=a.daemon_claims,lifecycle_store=a.lifecycle_store,inbox_root=a.inbox_root)
 except DiagnosticError as e:print(f"error: {e}",file=sys.stderr);return 1
 print(json.dumps(r,indent=2));return 0
if __name__=="__main__":raise SystemExit(main())
