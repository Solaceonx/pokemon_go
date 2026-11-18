"""Resume completed-source extraction/verification using saved source receipts."""
import argparse,concurrent.futures,json,os,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--work',type=Path,required=True)
    ap.add_argument('--reader',type=Path,required=True)
    ap.add_argument('--source',action='append',required=True)
    ap.add_argument('--jobs',type=int,default=3)
    a=ap.parse_args()
    if not 1<=a.jobs<=3:ap.error('Use at most three workers')
    def one(cid):
        folder=a.work/'runs'/cid;folder.mkdir(parents=True,exist_ok=True)
        base=[sys.executable,'-u']
        args=['--reader-dir',str(a.reader),'--library',str(a.work/'battles'),'--run-dir',str(folder)]
        for stage,command in [('extract',base+['scripts/recording/vod.py','https://www.twitch.tv/videos/'+cid,*args,'--sources-root',str(a.work/'sources'),'--jobs','1','--resegment']),('verify',base+['scripts/recording/vod_verify.py',cid,*args])]:
            with (folder/(stage+'-resumed.log')).open('w',encoding='utf-8') as stream:
                result=subprocess.run(command,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT)
            print(json.dumps({'source_id':cid,'stage':stage,'exit_code':result.returncode}),flush=True)
            if result.returncode:return {'source_id':cid,'stage':stage,'exit_code':result.returncode}
        return {'source_id':cid,'verified':True}
    with concurrent.futures.ThreadPoolExecutor(max_workers=a.jobs) as pool:results=list(pool.map(one,a.source))
    (a.work/'resumed-extraction.json').write_text(json.dumps(results,indent=2)+'\n',encoding='utf-8')
if __name__=='__main__':main()
