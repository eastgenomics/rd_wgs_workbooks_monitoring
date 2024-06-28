"""
Script to monitor state of eggd_generate_rd_wgs_workbook jobs and flag those
that have had workbooks made
"""
import ast
import dxpy as dx
import os
import argparse
import json

def parse_args() -> argparse.Namespace:
    """
    Parse command line arguments

    Returns
    -------
    args : Namespace
        Namespace of passed command line argument inputs
    """
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--json", "-i", required=True, help="DNAnexus file ID of GEL JSON"
    )
    parser.add_argument(
        "--dx_token", required=True, help="DNAnexus authentication token"
    )
    parser.add_argument(
        "--dx_project", required=True, help="DNAnexus project to query"
    )
    parser.add_argument(
        "--rnumber", required=True, help="GEL R number for family"
    )
    # TODO change below args to require=False once SHIRE integration is done
    parser.add_argument("--uid", required=False, help="uid to connect server")
    parser.add_argument(
        "--password", "-pw", required=False, help="password to connect server"
    )
    return parser.parse_args()

def dx_login(token):
    '''
    Function to check authenticating to DNAneuxs

    Parameters
    ----------
    token : str
        DNAnexus authentication token
    '''
    try:
        DX_SECURITY_CONTEXT = {
            "auth_token_type": "Bearer",
            "auth_token": str(token)
        }

        dx.set_security_context(DX_SECURITY_CONTEXT)
        dx.api.system_whoami()
    except dx.exceptions.InvalidAuthentication as err:
        print(err.error_message())

def find_jobs(dx_project):
    """
    Find eggd_generate_rd_wgs_workbook jobs jobs that have run in the given
    project in the last 48 hours

    Returns
    -------
    jobs : list
        list of describe objects for each job
    """
    jobs = list(dx.bindings.search.find_executions(
        project=dx_project,
        state='done',
        created_after='-12h',
        describe=True
    ))

    jobs = [
        x for x in jobs
        if x.get('describe', {}).get(
            'executableName'
        ) == 'eggd_generate_rd_wgs_workbook'
    ]

    print(
        f"Found the following {len(jobs)} eggd_generate_rd_wgs_workbook jobs: "
        f"{', '.join([x['id'] for x in jobs])}"
    )

    return jobs

def check_if_workbook_made(file_id, jobs):
    '''
    Check if a workbook has been made with the query GEL RD WGS JSON as an
    input
    '''
    matching_job = [
        x for x in jobs if
        x['describe']['input']['json']['$dnanexus_link'] == file_id
    ]

    job_id = ', '.join([x['id'] for x in matching_job])

    print(
        f"Found the eggd_generate_rd_wgs_workbook job {job_id} which has the "
        f"query JSON file ID {file_id} as an input"
    )
    return matching_job

def get_output_xlsx_file_id(job):
    '''
    Get the DNAnexus file ID of the output xlsx report from a given
    eggd_generate_rd_wgs_workbook job
    '''
    output_xlsx_id = job['describe']['output']['xlsx_report']['$dnanexus_link']
    return output_xlsx_id

def check_if_correct_json_downloaded(json_file_id, rnumber):
    '''
    Check that dx file is correct.
    '''
    with dx.open_dxfile(json_file_id, mode='r') as f:
        c = f.read()
    query_json = json.loads(c)
    # TODO change so this outputs to SHIRE
    if query_json['referral']['referral_id'] == rnumber:
        print(
            f"R number {rnumber} is present in {json_file_id}. "
            "Therefore correct file has been uploaded."
        )
    else:
        print(
            f"oh no! R number {rnumber} is NOT present in {json_file_id}"
        )

def monitor():
    '''
    Entry function
    '''
    print("Checking for eggd_generate_rd_wgs_workbook jobs...")

    args = parse_args()

    dx_login(args.dx_token)
    jobs = find_jobs(args.dx_project)

    job_using_json = check_if_workbook_made(args.json, jobs)
    if len(job_using_json) == 1:
        xlsx_id = get_output_xlsx_file_id(job_using_json[0])
        job_id = job_using_json[0]['id']
        print(
            f"Output .xlsx file from job with query JSON as an input found.\n "
            f"Job ID of the job is {job_id}.\nOutput xlsx file ID is {xlsx_id}"
        )
    else:
        raise RuntimeError(
            f"Multiple jobs found with file ID {args.json} as input."
        )

    check_if_correct_json_downloaded(args.json, args.rnumber)


if __name__ == "__main__":
    monitor()