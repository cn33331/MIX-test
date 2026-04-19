#!/bin/bash
PROFILE=$1

LOGCOLLECT_D=${LOGCOLLECT_D-"/mix/etc/scripts/logcollect.d"}
OUTPUT_DIR=/tmp/logcollect/logcollect_`date +"%Y%m%d_%H%M%S"`
OUTPUT_TGZ=${OUTPUT_DIR}.tgz

AVAILABLE_PROFILES=`for i in ${LOGCOLLECT_D}/*conf; do basename $i .conf; done`
MATCH=0
for p in ${AVAILABLE_PROFILES}; do
    if [ "$p" = "$PROFILE" ]; then
        MATCH=1
    fi
done
if [ "${MATCH}" != "1" ]; then
    echo "You must specify collection using one of these profiles: " ${AVAILABLE_PROFILES}
    #echo ${AVAILABLE_PROFILES}
    exit -1
fi

function copy() {
    echo "copy '$1' to '${OUTPUT_DIR}"
    for f in $1; do        
        if [ "$f" == "/var/log/journal" ]; then  # don't copy journal db.
            continue 
        fi
        DEST_DIR=${OUTPUT_DIR}/`dirname ${f}`
        mkdir -p ${DEST_DIR}
        if [ -f $f ] || [ -d $f ] ; then
            cp -r "$f" "${DEST_DIR}"
        else
            echo "$f" NOT FOUND
            NOT_FOUND_COOKIE=`basename "$f"`.not_found
            touch ${DEST_DIR}/${NOT_FOUND_COOKIE}
        fi
    done
}

function command() {
    echo "command '$1' --> ${2}"
    mkdir -p `dirname ${OUTPUT_DIR}/${2}`
    eval ${1} > ${OUTPUT_DIR}/${2}
}

function execute_job() {
    JOB_FILE=$1
    
    while IFS=$'\t' read -r TASK ARG1 ARG2; do

        TASK=`echo ${TASK} | xargs`
        ARG1=`echo ${ARG1} | xargs`
        ARG2=`echo ${ARG2} | xargs`
        
	    if [ "${TASK}" = "COPY" ]; then
            copy "${ARG1}"
        fi

        if [ "${TASK}" = "CMD" ]; then
            command "$ARG1" "$ARG2"
        fi
        
    done < $JOB_FILE

}


mkdir -p ${OUTPUT_DIR}

echo "Working on collection: '${PROFILE}'"
execute_job ${LOGCOLLECT_D}/${PROFILE}.conf

# Create archive
cd ${OUTPUT_DIR}
tar czf ${OUTPUT_TGZ} .

echo "Archive available: ${OUTPUT_TGZ}"
