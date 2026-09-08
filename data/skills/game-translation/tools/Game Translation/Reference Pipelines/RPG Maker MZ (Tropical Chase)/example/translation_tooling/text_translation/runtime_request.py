from pathlib import Path
import json,sys,time,uuid
HERE=Path(__file__).resolve().parent
def request(code,timeout=45):
    ident=uuid.uuid4().hex; q=HERE/'runtime'; q.mkdir(exist_ok=True)
    temp=q/'request.tmp'; temp.write_text(json.dumps({'id':ident,'code':code}),encoding='utf-8');temp.replace(q/'request.json')
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        try:
            result=json.loads((q/'response.json').read_bytes())
            if result.get('id')==ident:
                if not result['ok']: raise RuntimeError(result)
                return result['result']
        except (FileNotFoundError,json.JSONDecodeError): pass
        time.sleep(.15)
    raise TimeoutError(ident)
if __name__=='__main__':
    code=sys.stdin.read() if sys.argv[1]=='-' else Path(sys.argv[1]).read_text(encoding='utf-8') if sys.argv[1].endswith('.js') else sys.argv[1]
    print(json.dumps(request(code),ensure_ascii=True))
