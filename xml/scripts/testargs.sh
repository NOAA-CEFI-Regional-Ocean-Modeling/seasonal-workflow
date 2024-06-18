#!/bin/tcsh -f
if ( $#argv == 2 ) then 
	if ( "$argv[1]" == "-p" ) then
		set arg="${argv[2]}"
	endif 
else
	set arg=0
endif
echo ${arg}
echo "My name is ${arg}"
