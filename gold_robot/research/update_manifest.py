import hashlib, json
from pathlib import Path
root=Path(__file__).resolve().parents[1]
files=[p for p in (root/'INSTALL_ROBOT.bat',root/'README.txt',root/'INSTALL_FIX_README.txt') if p.is_file()]
for folder,extensions in [('mt5_robot',{'.mq5','.mqh','.ps1'}),('tests',{'.py','.mq5'}),('research',{'.py','.mq5','.ps1','.json'}),('docs',{'.md','.txt','.json'})]:
 files += [p for p in (root/folder).iterdir() if p.is_file() and p.suffix in extensions and p.name!='SOURCE_CHECKSUMS.json']
entries=[]
for p in sorted(files):
 b=p.read_bytes(); entries.append(dict(path=p.relative_to(root).as_posix(),bytes=len(b),sha256=hashlib.sha256(b).hexdigest()))
(root/'docs/SOURCE_CHECKSUMS.json').write_text(json.dumps({'sha256_files':entries},indent=2)+'\n',encoding='utf8')
print('Updated',len(entries),'source checksums')
