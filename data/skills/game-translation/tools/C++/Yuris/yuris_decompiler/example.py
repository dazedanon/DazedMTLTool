from yurislib import *
from yurislib import fileformat

# 1. YPF extractor
with open('example-files/v255.ypf', 'rb') as fp:
    YPF(fp).extract('example-files/v255')
with open('example-files/v494.ypf', 'rb') as fp:
    YPF(fp,
        name_encoding='cp932',
        name_size_trans=fileformat.NLTransV000,
        name_byte_trans=fileformat.NameXorV000,
        hash_name_file=fileformat.V470Hash
        ).extract('example-files/v494')

# 2. Decompile YSTB (need YSCom.ycd)
with open('example-files/v255.ycd', 'rb') as fp:
    yscd = YSCD(Rdr(fp.read()))

# use KEY_200 for v200-v289
y_decompile('example-files/v255/ysbin', 'example-out/v255', yscd, KEY_200)

# it can also work without YSCom, but compiler vars are needed to be fixed manually
# other encodings can be used for output, but sources will not be able to be compiled by YSCom
y_decompile('example-files/v255/ysbin', 'example-out/v255-no_yscom', None, KEY_200,
            o_encoding='utf-8')

with open('example-files/v494.ycd', 'rb') as fp:
    yscd = YSCD(Rdr(fp.read()))

# use KEY_300 for v290-v494
y_decompile('example-files/v494/ysbin', 'example-out/v494', yscd, KEY_300,
            i_encoding='cp932',
            o_encoding='cp932')
