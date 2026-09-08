#!/usr/bin/env python3
"""Local Tyrano extraction, estimate, validated import, and Claude batch commands."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parent/'scripts'))
import project as p
import claude_batch as b


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('extract')
    sub.add_parser('dryrun')
    sub.add_parser('lock-names')
    pre=sub.add_parser('prepare');pre.add_argument('--phase',choices=['names','text','all'],default='names');pre.add_argument('--limit',type=int)
    for command in ('submit','status','fetch'):
        cmd=sub.add_parser(command);cmd.add_argument('run')
    imp=sub.add_parser('import');imp.add_argument('file',type=Path);imp.add_argument('--overwrite',action='store_true')
    val=sub.add_parser('validate');val.add_argument('--complete',action='store_true')
    inj=sub.add_parser('inject');inj.add_argument('--identity',action='store_true');inj.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.command=='extract':result=p.extraction()
    elif args.command=='lock-names':
        with b.lock(p.ROOT):result=b.lock_names()
    elif args.command=='dryrun':
        _,req=b.make_requests();result=b.estimate(req);p.write_json(p.REPORTS/'estimate.json',result)
        if req:p.write_json(p.REPORTS/'sample_request.json',req[0])
    elif args.command=='prepare':result=b.prepare(args.phase,args.limit)
    elif args.command in ('submit','status','fetch'):result=getattr(b,args.command)(args.run)
    elif args.command=='import':
        with b.lock(p.ROOT):result={'imported':b.import_mapping(p.read_json(args.file),{'source':args.file.name},args.overwrite)}
    elif args.command=='validate':
        _,units=p.load_catalog();values=b.store()['translations'];ids={u.id for u in units}
        errors={u.id:p.validate_text(u,values[u.id]) for u in units if u.id in values}
        errors={k:v for k,v in errors.items() if v}
        result={'total':len(units),'translated':len(values),'missing':len(ids-set(values)),
                'unknown_ids':list(set(values)-ids),'errors':errors,'extraction_blockers':p.read_json(p.REPORTS/'blockers.json')}
        p.write_json(p.REPORTS/'validation.json',result)
        if errors or result['unknown_ids'] or result['extraction_blockers'] or args.complete and result['missing']:
            print(json.dumps(result,ensure_ascii=False,indent=2));return 1
    elif args.command=='inject':
        if not args.identity:
            raise ValueError('English deployment is not enabled in this preparation kit. Dynamic display mapping, final layout, and save/runtime checks must be wired before release. Use --identity for the verified byte-round-trip.')
        result=p.build_tree(args.output,identity=True);p.write_json(p.REPORTS/'identity.json',result)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0


if __name__=='__main__':
    try:sys.exit(main())
    except (ValueError,FileNotFoundError,FileExistsError) as exc:
        print(f'ERROR: {exc}',file=sys.stderr);sys.exit(2)
