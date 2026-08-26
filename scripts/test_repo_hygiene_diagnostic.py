#!/usr/bin/env python3
import tempfile
from pathlib import Path
import repo_hygiene_diagnostic as h
class P:
 def __init__(self,out="",code=0,err=""):self.stdout=out;self.returncode=code;self.stderr=err
calls=[]
FAKE_WT=Path.cwd()
def fake(cmd,**kw):
 calls.append((cmd,kw.get("cwd")))
 if cmd[:3]==["git","rev-parse","--path-format=absolute"]:return P("C:/primary/.git\n")
 if cmd[:3]==["git","worktree","list"]:return P(f"worktree {FAKE_WT}\nHEAD aaa\nbranch refs/heads/main\n\nworktree C:/missing\nHEAD bbb\ndetached\nprunable gitdir missing\n")
 if cmd[:3]==["git","status","--porcelain"]:return P(" M x\n")
 if cmd[:3]==["git","symbolic-ref","refs/remotes/origin/HEAD"]:return P("refs/remotes/origin/main\n")
 if cmd[:3]==["gh","pr","list"]:return P('[{"headRefName":"feat/x"}]')
 if cmd[:2]==["git","for-each-ref"]:return P("\0".join(["main","a","2026-08-25T00:00:00+00:00","origin/main","[ahead 1, behind 2]"])+"\n"+"\0".join(["feat/x","b","2026-08-25T00:00:00+00:00","origin/feat/x",""])+"\n")
 if cmd[:3]==["git","merge-base","--is-ancestor"]:return P(code=0 if cmd[3]=="main" else 1)
 if cmd[:3]==["git","rev-list","--left-right"]:return P("1 2\n")
 if cmd[:3]==["git","stash","list"]:return P("\0".join(["stash@{0}","2026-08-20 00:00:00 +0000","crash recovery"])+"\n")
 return P(code=2,err="unexpected")
def check(n,v):
 print(("ok " if v else "FAIL ")+n)
 if not v:raise AssertionError(n)
def main():
 root=Path(tempfile.mkdtemp());repo=root/"requested";repo.mkdir();box=root/"lab"/"inbox";(box/"coordinator"/"in").mkdir(parents=True);(root/"lab"/"a.md").write_text("x");(box/"coordinator"/"in"/"m.md").write_text("---\nfrom: a\nto: coordinator\ntype: delivery\ncreated: now\nartifact: a.md\naffects: docs\n---\nok");claims=root/"claims.json";claims.write_text('["x"]')
 r=h.diagnose(repo,runner=fake,daemon_claims=claims,inbox_root=box)
 check("HEAD-before-branch",r["worktrees"][0]["branch"]=="main");check("detached/prunable",r["worktrees"][1]["detached"] and r["worktrees"][1]["prunable"]);check("dirty/missing",r["worktrees"][0]["dirty"] and r["worktrees"][1]["dirty"] is None);check("cwd threaded",all(c for _,c in calls));check("origin preserved",r["remote_base"]=="refs/remotes/origin/main");check("ahead/behind/bound",r["branches"][0]["ahead"]==1 and r["branches"][0]["behind"]==2 and r["branches"][0]["worktree_bound"]);check("open PR",r["branches"][1]["category"]=="active-open-pr");check("stash",r["summary"]["stash_count"]==1);check("stores",r["daemon_claims"]["record_count"]==1 and r["lifecycle_store"]["status"]=="not_configured");m=r["inbox"]["messages"][0];check("inbox",not m["missing_fields"] and m["artifact_exists"])
 def bad(cmd,**kw):return P(code=1,err="down")
 try:h.diagnose(repo,runner=bad);ok=False
 except h.DiagnosticError:ok=True
 check("fail closed",ok);forbidden={"remove","delete","clean","prune","push","commit","add","pop","drop"};check("read only",not any(forbidden.intersection(c) for c,_ in calls));print("PASS")
if __name__=="__main__":main()
