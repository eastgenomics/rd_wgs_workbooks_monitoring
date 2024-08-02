"""
Script to launched eggd_generate_rd_wgs_workbook jobs, check inputs are correct
and update Shire with the output XLSX file ID
"""
import dxpy as dx
import argparse
import json
import pyodbc
import pandas as pd
import time


def parse_args():
    '''
    Parse command line arguments

    Returns
    -------
    args : Namespace
        Namespace of passed command line argument inputs
    '''
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--dx_token", required=True, help="DNAnexus authentication token"
    )
    parser.add_argument(
        "--config", required=False, help="Config with inputs for workbooks app"
    )
    parser.add_argument(
        "--testing", action=argparse.BooleanOptionalAction,
        help="If set to true will limit number of jobs launched to 5"
    )
    parser.add_argument("--uid", required=True, help="uid to connect server")
    parser.add_argument(
        "--password", "-pw", required=True, help="password to connect server"
    )
    return parser.parse_args()


def dx_login(token):
    '''
    Function to check authenticating to DNAnexus

    Inputs:
        token (str): DNAnexus authentication token
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


def check_if_correct_json_downloaded(json_file_id, rnumber, conn):
    '''
    Check that a given JSON file ID is for the given GEL family ID (R number)

    Inputs:
        json_file_id (str): DNAnexus file ID for a GEL RD WGS JSON
        rnumber (str): GEL family ID
        conn: pyodbc database connection
    '''
    with dx.open_dxfile(json_file_id, mode='r') as f:
        c = f.read()
    query_json = json.loads(c)

    if query_json['family_id'] == rnumber:
        query = (
            f"UPDATE dbo.CIPAPIReferralNumber SET StatusReferralNumberID = 6 "
            f"WHERE JSONFileID = '{json_file_id}' AND "
            f"ReferralNumber = '{rnumber}'"
        )
        update_shire(query, conn)
    else:
        query = (
            f"UPDATE dbo.CIPAPIReferralNumber SET StatusReferralNumberID = 7 "
            f"WHERE JSONFileID = '{json_file_id}' AND "
            f"ReferralNumber = '{rnumber}'"
        )
        update_shire(query, conn)


def update_shire(query, conn):
    '''
    Run a shire query to update the table

    Inputs:
        query (str): SQL query to use on database
        conn: pyodbc database connection
    '''
    cursor = conn.cursor()
    cursor.execute(query)
    conn.commit()


def monitor(jobs_launched, conn):
    '''
    Check jobs launched for completed jobs and update Shire database to
    change status for successful jobs to XlsxCreated and add the file ID.

    Inputs:
        jobs_launched (dict): dict of json file ID and DX job object
        conn: pyodbc database connection
    '''
    print("Checking status of eggd_generate_rd_wgs_workbook jobs...")

    for json_file_id, job in jobs_launched.items():
        status = job.describe().get('state')
        if status == 'done':
            xlsx_file_id = job.describe().get('input').get('json').get(
                '$dnanexus_link'
            )
            query = (
                "UPDATE dbo.CIPAPIReferralNumber "
                "SET StatusReferralNumberID = 9, "
                f"XLSXFileID = '{xlsx_file_id}' "
                f"WHERE JSONFileID = '{json_file_id}'"
            )
            update_shire(query, conn)
        else:
            job_id = job.describe().get('id')
            print(
                f"Job {job_id} for JSON {json_file_id} has status {status}. "
                "XLSX report not generated; record in Shire will remain in "
                "status DXJobStarted and will run again on next running of "
                "this script."
            )

    # Close connection
    conn.close()


def launch(args, conn):
    '''
    Check if R number in JSON matches desired R number, and if so launch
    eggd_generate_rd_wgs_workbook jobs for each JSON.

    Inputs:
        args: argparse Namespace of parsed command line arguments
        conn: pyodbc database connection
    '''
    query = (
        "SELECT * FROM dbo.CIPAPIReferralNumber WHERE StatusReferralNumberID "
        " = 5;"
    )
    df = pd.read_sql(query, conn)

    # If testing, limit to first five records in Shire.
    if args.testing is True:
        df = df.head()

    print(df)

    print("Checking that the R number in JSON is correct...")
    if not df.empty:
        for index, row in df.iterrows():
            rnumber = row['ReferralNumber']
            json_file_id = row["JSONFileID"]
            check_if_correct_json_downloaded(json_file_id, rnumber, conn)
    else:
        print("No records found in status JSONUploaded. Continuing...")

    print("Checking for records in status JSONCheckPass or DXJobStarted")
    query = (
        "Select * FROM dbo.CIPAPIReferralNumber WHERE StatusReferralNumberID "
        "IN (6, 8)"
    )

    df = pd.read_sql(query, conn)

    # Open config with eggd_generate_rd_wgs_workbook app inputs
    with open(args.config) as f:
        config = json.load(f)

    if df.empty:
        print("No records found with status JSONCheckPass or DXJobStarted")
        return None

    print("Launching DNAnexus jobs...")
    launched_jobs = {}
    for index, row in df.iterrows():
        rnumber = row['ReferralNumber']
        json_file_id = row["JSONFileID"]
        job = dx.DXApp(
            config["eggd_generate_rd_wgs_workbook_app_id"]
            ).run(
            app_input={
                'json': {
                    "$dnanexus_link": {
                        "project": 'project-GpV5V1j4f83q40F06kq5Gyx3',
                        "id": json_file_id
                    }
                },
                'refseq_tsv': config["inputs"]["refseq_tsv"],
                'mane_file': config["inputs"]["mane_file"],
                'config': config["inputs"][
                    "eggd_generate_rd_wgs_workbook_config"
                    ],
            },
            project='project-GpYqX00479VF40F06kq69Jjj',
            name=f'eggd_generate_rd_variant_workbook_{rnumber}'
        )

        job_id = job.describe().get('id')

        print(f"Launched DX job {job_id} for {rnumber} ({json_file_id})")
        launched_jobs[json_file_id] = job

        query = (
            f"UPDATE dbo.CIPAPIReferralNumber"
            " SET StatusReferralNumberID = 8 WHERE "
            f"JSONFileID = '{json_file_id}' AND ReferralNumber = '{rnumber}';"
        )
        update_shire(query, conn)

    return launched_jobs


def main():
    '''
    Entry function
    '''
    args = parse_args()

    dx_login(args.dx_token)

    # Establish connection
    conn_str = (
        f"DSN=gemini;DRIVER={{SQL Server Native Client 11.0}};"
        f"UID={args.uid};PWD={args.password}"
    )
    conn = pyodbc.connect(conn_str)

    # Launch the jobs
    jobs = launch(args, conn)

    if jobs is not None:
        # Wait 15 mins to allow jobs to complete (each job takes about 3 mins)
        print("Pausing to allow jobs to complete...")
        time.sleep(900)

        # Monitor the jobs
        monitor(jobs, conn)


if __name__ == "__main__":
    main()
