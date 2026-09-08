"""Capture a single specified native QA window; never capture the desktop."""
import ctypes as c,sys
from ctypes import wintypes as w
from PIL import Image
u=c.WinDLL('user32');g=c.WinDLL('gdi32')
u.GetWindowDC.argtypes=[w.HWND];u.GetWindowDC.restype=w.HDC
u.ReleaseDC.argtypes=[w.HWND,w.HDC]
u.GetWindowRect.argtypes=[w.HWND,c.POINTER(w.RECT)]
u.PrintWindow.argtypes=[w.HWND,w.HDC,w.UINT]
g.CreateCompatibleDC.argtypes=[w.HDC];g.CreateCompatibleDC.restype=w.HDC
g.CreateCompatibleBitmap.argtypes=[w.HDC,c.c_int,c.c_int];g.CreateCompatibleBitmap.restype=w.HBITMAP
g.SelectObject.argtypes=[w.HDC,w.HGDIOBJ];g.SelectObject.restype=w.HGDIOBJ
g.GetDIBits.argtypes=[w.HDC,w.HBITMAP,w.UINT,w.UINT,c.c_void_p,c.c_void_p,w.UINT]
g.DeleteObject.argtypes=[w.HGDIOBJ];g.DeleteDC.argtypes=[w.HDC]
class Header(c.Structure):
 _fields_=[('size',w.DWORD),('width',w.LONG),('height',w.LONG),('planes',w.WORD),('bpp',w.WORD),('compression',w.DWORD),('image_size',w.DWORD),('xppm',w.LONG),('yppm',w.LONG),('used',w.DWORD),('important',w.DWORD)]
hwnd=int(sys.argv[1]);rect=w.RECT();assert u.GetWindowRect(hwnd,c.byref(rect))
width,height=rect.right-rect.left,rect.bottom-rect.top
assert 400<=width<=2000 and 300<=height<=2000,(width,height)
dc=u.GetWindowDC(hwnd);mem=g.CreateCompatibleDC(dc);bitmap=g.CreateCompatibleBitmap(dc,width,height);old=g.SelectObject(mem,bitmap)
try:
 assert u.PrintWindow(hwnd,mem,2),'PrintWindow failed'
 g.SelectObject(mem,old)
 header=Header(c.sizeof(Header),width,-height,1,32,0,width*height*4,0,0,0,0)
 buf=c.create_string_buffer(width*height*4)
 assert g.GetDIBits(mem,bitmap,0,height,buf,c.byref(header),0)==height
 Image.frombytes('RGB',(width,height),buf.raw,'raw','BGRX').save(sys.argv[2])
 print({'width':width,'height':height,'path':sys.argv[2]})
finally:
 g.DeleteObject(bitmap);g.DeleteDC(mem);u.ReleaseDC(hwnd,dc)
