from os import makedirs, path
from yuri.fileformat import *
import yuri.yuridec as yuridec
import yuri.yuricom as yuricom
from multiprocessing import freeze_support

# Windows need this for multiprocessing
if __name__ == '__main__':
    freeze_support()

# Parameters for YPF decompression
YPF_IN  = path.join('ypf', 'ysbin-input.ypf') # Input path for the original YPF file
YPF_EX  = path.join('ybn', 'original')     # Output extracted files from input YPF

## Get the actual version of the input YPF file
with open(YPF_IN, 'rb') as ypfinobject:
    ypf_in_entries, ypf_in_version = ypf_read(ypfinobject)
    print('The actual version of the YPF file is:', ypf_in_version)

## Extract the files from the input YPF file to the given YPF_EX folder
for file_path, file_type, compressed, file_data, uncompressed_length in ypf_in_entries:
    print('Extracted file: ' + file_path)
    file_path_full = path.join(YPF_EX, *file_path.split('\\'))
    makedirs(path.dirname(file_path_full), exist_ok=True)
    # Save the file to the output path
    with open(file_path_full, 'wb') as extracted_ypf_object:
        extracted_ypf_object.write(file_data)


## Parameters for YBN compilation/decompilation, and YPF creation
YPF_VER = ypf_in_version  # Version of the YPF file reported in its header.
YBN_VER_ACTUAL = 480 # Version of the YBN files, which those can be different from the version the game's main executable may say. That can be obtained through trial and error by doing decompilations, and seeing which version does it successfully.
YCD = path.join('YSCom', str(YPF_VER) + '.ycd') # Official YSCom.ycd compiler
YBN_IN = path.join(YPF_EX, 'ysbin') # Input path of the original YBN files obtained from the YPF file
YSTB_KEY = 0x9C28430c # XOR key of the YSTB files (the ones that are called yst00000.ybn up to the last number). For more information on what key to use check the notes in the repository.
YSB_OUT_OFFICIAL = path.join('ybn', 'decoded', 'official') # Output path for the decoded YBN files using the official compiler (only useful that games that can be recompiled back with the official compiler)
YSB_OUT_UNOFFICIAL = path.join('ybn', 'decoded', 'unofficial') # Output path for the decoded YBN files using the custom YURI syntax (useful for games that cannot be recompiled back with the official compiler)
YBN_VER = 554 # Version of the YBN files, which may differ from the ones present in the YBN files themselves. In this case it is important to check the header of the YPF input file to ensure that the correct version is selected.
YPF_OUT = path.join('ypf', 'ysbin-output.ypf') # Path of the resulting YPF file when compiling using the custom YURI syntax
YSB_OUT_UNOFFICIAL_TEMP = path.join('ybn', 'encoded', 'temp')

# ## Load official YU-RIS compiler, used for recovering the system variable names
# with open(YCD, 'rb') as ycdobject:
#     yscd = YSCD.read(Rdr.from_bio(ycdobject))
#     cdict = {v.name: (v.typ, i) for i, v in enumerate(yscd.vars)}

# # Decompile the given YBN files in YBN_IN to the given YSB_OUT_OFFICIAL path using the official compiler syntax
# yuridec.run(YBN_IN, YSB_OUT_OFFICIAL, 
#             ienc='CP932', oenc='CP932', 
#             yscd=yscd, dcls=yuridec.YDecYuris, mp_parallel=False, also_dump=False, 
#             key=YSTB_KEY, ver=YPF_VER) #If YPF_VER does not work, YBN_VER_ACTUAL will come in place

# Decompile the given YBN files in YBN_IN to the given YSB_OUT_UNOFFICIAL path using the custom YURI syntax
yuridec.run(YBN_IN, YSB_OUT_UNOFFICIAL, 
            ienc=CP932, oenc='utf-8', 
            dcls=yuridec.YDecYuri, mp_parallel=False, also_dump=True, 
            key=YSTB_KEY, ver=YBN_VER_ACTUAL) #If YPF_VER does not work, YBN_VER_ACTUAL will come in place

# Compile the given decompiled YBN files in YSB_OUT_UNOFFICIAL using the custom YURI syntax
yuricom.run(
    key=YSTB_KEY,
    iroot=YSB_OUT_UNOFFICIAL,
    ver=YBN_VER_ACTUAL,  # Version of the YBN files, the one reported inside the YSB files themselves
    wroot=YSB_OUT_UNOFFICIAL_TEMP,  # Temporary directory for the compiler
    troot=YBN_IN,  # For some original ybn files from the game (specifically the ysv, ysc, yse, yscfg ones)
    o_ypf=YPF_OUT,  # Output path of the resulting .ypf file
    i_enc='utf-8', # Encoding of strings in YSTB
    o_enc=CP932, # encoding in troot files
    t_ver=YBN_VER_ACTUAL,  # Here goes the version the game has in the YBN files
    w_ver=YBN_VER,  # While in theory this shouldn't change for the YBN files, some custom games have a different version, and that is indicated in the YPF file (check the header of the original YBN file to know which version is)
    mp_parallel=False,
    ypf_ver=YPF_VER,  # Here goes the version the game reports in the YPF file
    opts=yuricom.ComOpts(opt_custom_npar=False) # Here we indicate if the GOSUB_NPAR is defined differently than the standard SDK does. For more information, check [this file](yuri.md#gosub_npar) for more information.
)