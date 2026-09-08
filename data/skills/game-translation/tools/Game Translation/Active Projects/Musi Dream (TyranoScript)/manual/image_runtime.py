"""Read-only image decode QA against an already-running isolated game.

Usage after the final image build has been installed in translation/test_game
and launched with the existing launch_test.ps1 (port 9222):

    python translation/manual/image_runtime.py

This script never launches the game, navigates, clicks, changes Tyrano state,
inserts DOM nodes, or loads the excluded image. Each translated ASAR file is
loaded with a temporary Image and drawn at native size into a detached canvas.
Pillow independently supplies the expected RGBA and premultiplied RGBA hashes.
Report: reports/image_decode.json. Visible scene QA is assembled separately.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import sys
import time
from urllib.parse import quote, unquote, urlsplit

import numpy as np
from PIL import Image, ImageCms
from cdp_client import CDPClient

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from unpack_app import read_header, iter_entries


DECODE_JS=r"""(async () => {
  const spec = __SPEC__;
  const result = {path: spec.path, url: spec.url};
  const hasCrypto = !!(globalThis.crypto && crypto.subtle);
  const hex = bytes => Array.from(new Uint8Array(bytes),x=>x.toString(16).padStart(2,'0')).join('');
  const sha = async bytes => hasCrypto ? hex(await crypto.subtle.digest('SHA-256',bytes)) : null;
  const b64 = bytes => {
    let pieces=[];
    for(let i=0;i<bytes.length;i+=32768) pieces.push(String.fromCharCode.apply(null,bytes.subarray(i,i+32768)));
    return btoa(pieces.join(''));
  };
  let img, timer;
  try {
    // The URL is a validated local file inside the pinned fixture app.asar.
    // fetch is an extra encoded-byte check; canvas decoding does not depend on it.
    try {
      const response=await fetch(spec.url,{cache:'no-store'});
      if(!response.ok) throw new Error('HTTP '+response.status);
      const encoded=new Uint8Array(await response.arrayBuffer());
      result.encoded_bytes=encoded.length;
      result.encoded_sha256=await sha(encoded);
      if(!hasCrypto) result.encoded_base64=b64(encoded);
    } catch(e) { result.encoded_fetch_error=String(e); }
    img=new Image();
    await new Promise((resolve,reject)=>{
      timer=setTimeout(()=>reject(new Error('Image.onload timed out')),spec.timeout_ms);
      img.onload=()=>{clearTimeout(timer);resolve();};
      img.onerror=()=>{clearTimeout(timer);reject(new Error('Image.onerror'));};
      img.src=spec.url;
    });
    result.width=img.naturalWidth; result.height=img.naturalHeight;
    if(!result.width || !result.height) throw new Error('Decoded image has no pixels');
    const canvas=document.createElement('canvas'); // Never appended to the document.
    canvas.width=result.width; canvas.height=result.height;
    const ctx=canvas.getContext('2d',{willReadFrequently:true,colorSpace:'srgb'});
    if(!ctx) throw new Error('2D canvas unavailable');
    ctx.imageSmoothingEnabled=false;
    ctx.drawImage(img,0,0);
    const pixels=ctx.getImageData(0,0,canvas.width,canvas.height).data;
    result.rgba_sha256=await sha(pixels);
    const pm=new Uint8Array(pixels.length);
    for(let i=0;i<pixels.length;i+=4) {
      const alpha=pixels[i+3];
      pm[i]=Math.floor((pixels[i]*alpha+127)/255);
      pm[i+1]=Math.floor((pixels[i+1]*alpha+127)/255);
      pm[i+2]=Math.floor((pixels[i+2]*alpha+127)/255);
      pm[i+3]=alpha;
    }
    result.premultiplied_rgba_sha256=await sha(pm);
    if(!hasCrypto || result.premultiplied_rgba_sha256!==spec.expected_pm_sha256) {
      result.rgba_base64=b64(pixels);
    }
    result.complete=img.complete;
    result.canvas_attached=canvas.isConnected;
    result.image_attached=img.isConnected;
    canvas.width=0; canvas.height=0;
    return result;
  } catch(e) {
    result.error=String(e); return result;
  } finally {
    clearTimeout(timer);
    if(img) {img.onload=null;img.onerror=null;img.removeAttribute('src');}
  }
})()"""


def file_sha(path: Path) -> str:
    with path.open('rb') as fh:return hashlib.file_digest(fh,'sha256').hexdigest()


def bytes_sha(value: bytes) -> str:return hashlib.sha256(value).hexdigest()


def premultiply(rgba: np.ndarray) -> np.ndarray:
    result=rgba.copy()
    result[...,:3]=((rgba[...,:3].astype(np.uint16)*rgba[...,3:4].astype(np.uint16)+127)//255).astype(np.uint8)
    return result


def expected_pixels(im: Image.Image) -> tuple[np.ndarray,dict]:
    """Canvas is sRGB; honor embedded profiles before comparing its pixels.

    Chromium's color conversion and LittleCMS round a small subset of channels
    differently. Only tagged images receive a one-level RGB tolerance; their
    alpha values and encoded file hashes must still match exactly.
    """
    if im.info.get('icc_profile'):
        profile=ImageCms.ImageCmsProfile(io.BytesIO(im.info['icc_profile']))
        converted=ImageCms.profileToProfile(im,profile,ImageCms.createProfile('sRGB'),
                                            renderingIntent=0,outputMode='RGBA')
        return np.array(converted),{'embedded_profile':ImageCms.getProfileDescription(profile).strip(),
                                    'conversion':'LittleCMS embedded profile to sRGB',
                                    'rgb_rounding_tolerance':1}
    return np.array(im.convert('RGBA')),{'rgb_rounding_tolerance':0}


def safe_relative(value: str) -> str:
    if not isinstance(value,str) or '\\' in value or ':' in value or '\x00' in value:
        raise ValueError(f'Invalid archive path: {value!r}')
    path=PurePosixPath(value)
    if path.is_absolute() or any(x in ('','.','..') for x in value.split('/')):
        raise ValueError(f'Invalid archive path: {value!r}')
    return path.as_posix()


def target_is_fixture(url: str, archive: Path) -> bool:
    parsed=urlsplit(url)
    if parsed.scheme!='file' or parsed.netloc not in ('','localhost'):return False
    decoded=unquote(parsed.path).lstrip('/').replace('\\','/').casefold()
    prefix=archive.resolve().as_posix().lstrip('/').casefold()+'/'
    return decoded.startswith(prefix)


def game_snapshot(cdp: CDPClient) -> dict:
    return cdp.evaluate("""(() => {
      const k=globalThis.TYRANO && TYRANO.kag;
      return {url:location.href,document_nodes:document.getElementsByTagName('*').length,
              scenario:k&&k.stat.current_scenario,order_index:k&&k.ftag.current_order_index};
    })()""")


def preflight(manifest_path: Path, archive: Path) -> tuple[dict,list[dict]]:
    document=json.loads(manifest_path.read_text(encoding='utf-8-sig'))
    if document.get('format_version')!=1 or not isinstance(document.get('assets'),list):
        raise ValueError('Expected image manifest format_version 1 with assets array')
    inventory=json.loads((ROOT/'images/inventory.json').read_text(encoding='utf-8-sig'))
    excluded_reference=next(r for r in inventory if r['id']==6)
    excluded={r['path'] for r in inventory if r['sha256']==excluded_reference['sha256']}
    excluded.add(excluded_reference['path'])
    header,offset=read_header(archive)
    entries=dict(iter_entries(header)); assets=[]; seen=set()
    with archive.open('rb') as fh:
        for asset in document['assets']:
            rel=safe_relative(asset['path'])
            if rel in seen:raise ValueError(f'Duplicate manifest path: {rel}')
            if rel in excluded:raise ValueError('Excluded image unexpectedly appears in image manifest')
            if asset.get('status')!='rendered' or asset.get('reviewed') is not True:
                raise ValueError(f'Image is not reviewed and rendered: {rel}')
            seen.add(rel)
            output=ROOT/'images/output'/rel
            if file_sha(output)!=asset['output_sha256']:
                raise ValueError(f'Output hash mismatch: {rel}')
            entry=entries.get(rel)
            if not entry or entry.get('unpacked') or entry.get('link') or 'offset' not in entry:
                raise ValueError(f'Image is not a packed archive entry: {rel}')
            pos=offset+int(entry['offset']); size=int(entry['size'])
            if pos<offset or size<1 or pos+size>archive.stat().st_size:
                raise ValueError(f'Archive image bounds invalid: {rel}')
            fh.seek(pos); actual_sha=bytes_sha(fh.read(size))
            if actual_sha!=asset['output_sha256']:
                raise ValueError(f'Fixture does not contain the reviewed image: {rel}')
            with Image.open(output) as im:
                if (im.width,im.height)!=(asset['width'],asset['height']):
                    raise ValueError(f'Manifest dimensions mismatch: {rel}')
                if getattr(im,'n_frames',1)!=1:
                    raise ValueError(f'Translated animated asset needs frame-aware QA: {rel}')
                rgba,color=expected_pixels(im)
                expected={'width':im.width,'height':im.height,'mode':im.mode,'format':im.format,
                          'color_management':color,
                          'rgba_sha256':bytes_sha(rgba.tobytes()),
                          'premultiplied_rgba_sha256':bytes_sha(premultiply(rgba).tobytes())}
            assets.append({'path':rel,'output_sha256':asset['output_sha256'],
                           'archive_entry_sha256':actual_sha,'expected':expected})
    if not assets:raise ValueError('The image manifest is empty')
    if any((ROOT/'images/output'/rel).exists() for rel in excluded):
        raise ValueError('An output exists for an excluded image')
    return {'excluded_paths':sorted(excluded),'excluded_outputs_absent':True,
            'excluded_manifest_entries_absent':True,'excluded_browser_loads':0},assets


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--manifest',type=Path,default=ROOT/'images/manifest.json')
    parser.add_argument('--port',type=int,default=9222)
    parser.add_argument('--target',help='Optional CDP page target ID')
    parser.add_argument('--timeout',type=float,default=30.0,help='Per-image CDP timeout in seconds')
    parser.add_argument('--preflight-only',action='store_true',help='Verify files without contacting a browser; does not create a passing runtime report')
    args=parser.parse_args()
    if not 1<=args.timeout<=60:parser.error('--timeout must be between 1 and 60 seconds')
    archive=(ROOT/'test_game/resources/app.asar').resolve()
    manifest_path=args.manifest.resolve()
    report={'scope':'Read-only native-size image decoding from isolated game ASAR URLs; visible scene QA is recorded separately.',
            'archive':str(archive),'manifest':str(manifest_path),'passed':False,'assets':[],
            'comparison':'Encoded archive entries must match reviewed outputs. Exact premultiplied RGBA equality handles alpha round trips. Embedded ICC profiles are independently converted to sRGB with LittleCMS; only those images allow one RGB level of conversion rounding, with exact alpha.',
            'started_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())}
    try:
        report['archive_sha256']=file_sha(archive)
        report['image_manifest_sha256']=file_sha(manifest_path)
        report['exclusions'],assets=preflight(manifest_path,archive)
        report['expected_image_count']=len(assets)
        if args.preflight_only:
            print(json.dumps({'preflight_passed':True,'images':len(assets),
                              'archive_sha256':report['archive_sha256'],
                              'image_manifest_sha256':report['image_manifest_sha256']},indent=2))
            return 0
        with CDPClient(port=args.port,target_id=args.target,timeout=args.timeout,url_contains='app.asar/') as cdp:
            snapshot=game_snapshot(cdp)
            if not target_is_fixture(snapshot['url'],archive):
                raise ValueError('Debugger target is not the pinned translation/test_game archive')
            report['target']=cdp.target
            report['state_before']=snapshot
            for asset in assets:
                rel=asset['path'];expected=asset['expected']
                url=archive.as_uri()+'/'+quote(rel,safe='/')+'?image-qa='+report['image_manifest_sha256'][:16]
                spec={'path':rel,'url':url,'timeout_ms':max(1000,int((args.timeout-2)*1000)),
                      'expected_pm_sha256':expected['premultiplied_rgba_sha256']}
                expression=DECODE_JS.replace('__SPEC__',json.dumps(spec,ensure_ascii=True))
                actual=cdp.evaluate(expression,timeout=args.timeout)
                encoded_b64=actual.pop('encoded_base64',None)
                if encoded_b64 is not None:actual['encoded_sha256']=bytes_sha(base64.b64decode(encoded_b64,validate=True))
                rgba_b64=actual.pop('rgba_base64',None)
                if rgba_b64 is not None:
                    raw=base64.b64decode(rgba_b64,validate=True)
                    rgba=np.frombuffer(raw,dtype=np.uint8).reshape((actual['height'],actual['width'],4))
                    actual['rgba_sha256']=bytes_sha(raw)
                    actual['premultiplied_rgba_sha256']=bytes_sha(premultiply(rgba).tobytes())
                    if actual['premultiplied_rgba_sha256']!=expected['premultiplied_rgba_sha256'] and (actual['width'],actual['height'])==(expected['width'],expected['height']):
                        with Image.open(ROOT/'images/output'/rel) as im:pillow,_=expected_pixels(im)
                        delta=np.abs(premultiply(rgba).astype(np.int16)-premultiply(pillow).astype(np.int16))
                        actual['pixel_mismatch']={'pixels':int(np.any(delta,axis=2).sum()),'max_channel_delta':int(delta.max()),'alpha_mismatches':int((rgba[...,3]!=pillow[...,3]).sum())}
                mismatch=actual.get('pixel_mismatch',{})
                exact=actual.get('premultiplied_rgba_sha256')==expected['premultiplied_rgba_sha256']
                managed=expected['color_management']['rgb_rounding_tolerance']==1 and mismatch.get('max_channel_delta',256)<=1 and mismatch.get('alpha_mismatches',1)==0
                checks={'loaded':not actual.get('error') and actual.get('complete') is True,
                        'dimensions_match':(actual.get('width'),actual.get('height'))==(expected['width'],expected['height']),
                        'premultiplied_rgba_match':actual.get('premultiplied_rgba_sha256')==expected['premultiplied_rgba_sha256'],
                        'raw_rgba_match':actual.get('rgba_sha256')==expected['rgba_sha256'],
                        'color_managed_pixels_match':exact or managed,
                        'no_dom_insertion':actual.get('canvas_attached') is False and actual.get('image_attached') is False,
                        'encoded_browser_hash_matches':actual.get('encoded_sha256') in (None,asset['output_sha256'])}
                passed=all(v for k,v in checks.items() if k not in ('raw_rgba_match','premultiplied_rgba_match'))
                report['assets'].append({**asset,'actual':actual,'checks':checks,'passed':passed})
                print(('PASS' if passed else 'FAIL')+' '+rel,flush=True)
            report['state_after']=game_snapshot(cdp)
        report['archive_sha256_after']=file_sha(archive)
        report['image_manifest_sha256_after']=file_sha(manifest_path)
        report['archive_unchanged_during_check']=report['archive_sha256_after']==report['archive_sha256']
        report['manifest_unchanged_during_check']=report['image_manifest_sha256_after']==report['image_manifest_sha256']
        report['passed']=all(a['passed'] for a in report['assets']) and len(report['assets'])==len(assets) and report['archive_unchanged_during_check'] and report['manifest_unchanged_during_check']
    except Exception as exc:
        report['error']=str(exc)
        print('FAIL: '+str(exc),file=sys.stderr)
    finally:
        if not args.preflight_only:
            report['finished_utc']=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())
            payload=json.dumps(report,ensure_ascii=False,indent=2)+'\n'
            (ROOT/'reports').mkdir(exist_ok=True)
            (ROOT/'reports/image_decode.json').write_text(payload,encoding='utf-8')
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
