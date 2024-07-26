from calendar import isleap, monthrange
from textwrap import dedent
import os

def write_xml(common, ystart, mstart, extract_dir, scripts_dir,config_file):
    ystart = int(ystart)
    mstart = int(mstart)
    # Figure out what the date span 
    # used in the atmosphere filenames will be
    if isleap(ystart) and mstart == 3:
        # March 1 on leap year starts is named Feb 29
        mfirst = 2
        dfirst = 29
    else:
        mfirst = mstart
        dfirst = 1
    if mstart == 1:
        # January starts end in the same year
        yend = ystart
        mlast = 12
    else:
        # All other starts end in the next year
        yend = ystart + 1
        mlast = mstart - 1
    # Last day is always the last day of the last month
    dlast = monthrange(yend, mlast)[1]
    # Make sure that scripts and extract paths end in backslash
    scripts_dir = os.path.normpath(scripts_dir)
    extract_dir = os.path.normpath(extract_dir)
    #if scripts_dir[-1] == '/':
    #    scripts_dir = scripts_dir[:-1] 
    #if extract_dir[-1] == '/':
    #    extract_dir = extract_dir[:-1]
    # Make sure that the extract_dir ends in "extracted"
    if os.path.basename(extract_dir) != 'extracted':
        extract_dir += '/extracted'
    # Fill out the XML template
    xml = dedent(f'''    <?xml version="1.0"?>
    <experimentSuite rtsVersion="4" xmlns:xi="http://www.w3.org/2001/XInclude">
      <property name="ystart" value="{ystart}"/>
      <property name="mstart" value="{mstart:02d}"/>
      <property name="yend" value="{yend}"/>
      <property name="mend" value="{mlast:02d}"/>
      <property name="atmosspan" value="{ystart}{mfirst:02d}{dfirst:02d}-{yend}{mlast:02d}{dlast:02d}"/>
      <property name="extract_dir" value="{extract_dir}"/>
      <property name="scripts_dir" value="{scripts_dir}"/>
      <property name="config_file" value="{config_file}"/>
      <xi:include href="{common}" xpointer="xpointer(//freInclude[@name='common']/node())"/>
    </experimentSuite>''')
    # Write to file. The name will be based on the name of the common XML,
    # minus the "common"
    fname = common.replace('_common.xml', '')
    with open(f'{fname}_{ystart}-{mstart:02d}.xml', 'w') as f:
        f.write(xml)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('common', type=str)
    parser.add_argument('ystart', type=int)
    parser.add_argument('mstart', type=int)
    parser.add_argument('extract_dir', type=str)
    parser.add_argument('scripts_dir', type=str)
    parser.add_argument('config_file', type=str)
    args = parser.parse_args()
    write_xml(args.common, args.ystart, args.mstart, args.extract_dir, args.scripts_dir, args.config_file )

