"""This module contains the main process of the robot."""
import json
from OpenOrchestrator.orchestrator_connection.connection import OrchestratorConnection
from office365.runtime.auth.user_credential import UserCredential
from office365.sharepoint.client_context import ClientContext
import os
from urllib.parse import urlparse, parse_qs, unquote
from OpenOrchestrator.database.queues import QueueElement
from datetime import datetime
import calendar
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
import time
from urllib.parse import unquote, urlparse
import win32com.client as win32


def process(orchestrator_connection: OrchestratorConnection, queue_element: QueueElement | None = None) -> None:
        #Connect to orchestrator
    orchestrator_connection = OrchestratorConnection("PythonOpusBookMark", os.getenv('OpenOrchestratorSQL'),os.getenv('OpenOrchestratorKey'), None)

    log = True

    if log:
        orchestrator_connection.log_info("Started process")

    #Opus bruger
    OpusLogin = orchestrator_connection.get_credential("OpusBruger")
    OpusUser = OpusLogin.username
    OpusPassword = OpusLogin.password 

    #Robotpassword
    RobotCredential = orchestrator_connection.get_credential("Robot365User") 
    RobotUsername = RobotCredential.username
    RobotPassword = RobotCredential.password

    # Define the queue name
    queue_name = "OpusBookmarkQueue" 

    # Assign variables from SpecificContent
    OpusBookmark = None
    SharePointURL = None
    FileName = None
    Daily = None
    MonthEnd = None
    MonthStart = None
    Yearly = None

    # Get all queue elements with status 'New'
    queue_item = orchestrator_connection.get_next_queue_element(queue_name)
    if not queue_item:
        orchestrator_connection.log_info("No new queue items to process.")
        exit()

    specific_content = json.loads(queue_item.data)
    # specific_content = queue_item

    if log:
        orchestrator_connection.log_info("Assigning variables")

    # Assign variables from SpecificContent
    BookmarkID = specific_content.get("Bookmark")
    OpusBookmark = orchestrator_connection.get_constant("OpusBookMarkUrl").value + BookmarkID
    SharePointURL =  orchestrator_connection.get_constant("LauraTestSharepointURLFullPath").value ######Slet efter test - slet også konstant i OO
    #SharepointURL = specific_content.get("SharePointMappeLink", None)
    FileName = specific_content.get("Filnavn", None)
    Daily = specific_content.get("Dagligt (Ja/Nej)", None)
    MonthEnd = specific_content.get("MånedsSlut (Ja/Nej)", None)
    MonthStart = specific_content.get("MånedsStart (Ja/Nej)", None)
    Yearly = specific_content.get("Årligt (Ja/Nej)", None)
    # Mark the queue item as 'In Progress'
    orchestrator_connection.set_queue_element_status(queue_item.id, "IN_PROGRESS")

    # Mark the queue item as 'Done' after processing
    orchestrator_connection.set_queue_element_status(queue_item.id, "DONE")

    Run = False

    #Testing if it should run
    if Daily.lower() == "ja":
        Run = True
    else:
        current_date = datetime.now()
        year, month, day = current_date.year, current_date.month, current_date.day
        
        # Check for month-end
        last_day_of_month = calendar.monthrange(year, month)[1]  
        if MonthEnd.lower() == "ja" and day == last_day_of_month:
            Run = True
        # Check for month-start
        elif MonthStart.lower() == "ja" and day == 1:
            Run = True
        # Check for year-end
        elif Yearly.lower() == "ja" and day == 31 and month == 12:
            Run = True
        
    if Run:
        def convert_xls_to_xlsx(path: str) -> None:
            absolute_path = os.path.abspath(path)
            excel = win32.gencache.EnsureDispatch('Excel.Application')
            wb = excel.Workbooks.Open(absolute_path)

            # FileFormat=51 is for .xlsx extension
            new_path = os.path.splitext(absolute_path)[0] + ".xlsx"
            wb.SaveAs(new_path, FileFormat=51)
            wb.Close()
            excel.Application.Quit()    
            if os.path.exists(absolute_path):
                os.remove(absolute_path)


        # SharePoint credentials
        if log:
            orchestrator_connection.log_info("Connecting to sharepoint")
        SharepointURL_connection = orchestrator_connection.get_constant("LauraTestSharepointURL").value
        ####Den rigtige adgang skal bruges --- bare fx aarhuskommune osv, eller??

        #Connecting to sharepoint
        credentials = UserCredential(RobotUsername, RobotPassword)
        ctx = ClientContext(SharepointURL_connection).with_credentials(credentials)

        #Checking connection
        web = ctx.web
        ctx.load(web)
        ctx.execute_query()

        # Selenium configuration
        downloads_folder = os.path.join(os.path.expanduser("~"), "Downloads")
        file_path = os.path.join(downloads_folder, FileName + ".xlsx")

        # Delete the file if it exists in the Downloads folder
        if os.path.exists(file_path):
            os.remove(file_path)
        chrome_options = Options()
        chrome_options.add_experimental_option("prefs", {
            "download.default_directory": downloads_folder,
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
        })
        chrome_service = Service()  # Dynamically locate ChromeDriver if required
        driver = webdriver.Chrome(service=chrome_service, options=chrome_options)

        try:
            # Step 1: Navigate to the Opus portal and log in
            driver.get(orchestrator_connection.get_constant("OpusAdgangUrl").value)
            WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "logonuidfield")))
            
            username_field = driver.find_element(By.ID, "logonuidfield")
            password_field = driver.find_element(By.ID, "logonpassfield")
            username_field.send_keys(OpusUser)
            password_field.send_keys(OpusPassword)
            driver.find_element(By.ID, "buttonLogon").click()

            # Step 2: Navigate to the specific bookmark
            driver.get(OpusBookmark)
            WebDriverWait(driver, 20).until(
                EC.frame_to_be_available_and_switch_to_it((By.CSS_SELECTOR, "iframe[id^='iframe_Roundtrip']"))
            )

            # Step 3: Wait for the export button to appear
            WebDriverWait(driver, 60).until(
                EC.presence_of_element_located((By.ID, "ACTUAL_DATE_TEXT_TextItem"))
            )
            driver.find_element(By.ID, "BUTTON_EXPORT_btn1_acButton").click()

            # Step 4: Wait for the file download to complete
            initial_file_count = len(os.listdir(downloads_folder))
            start_time = time.time()
            while True:
                files = os.listdir(downloads_folder)
                if len(files) > initial_file_count:
                    latest_file = max(
                        [os.path.join(downloads_folder, f) for f in files], key=os.path.getctime
                    )
                    if latest_file.endswith(".xls"):
                        new_file_path = os.path.join(downloads_folder, f"{FileName}.xls")
                        os.rename(latest_file, new_file_path)

                        break
                if time.time() - start_time > 1800:  # Timeout after 30 minutes
                    raise TimeoutError("File download did not complete within 30 minutes.")
                time.sleep(1)
            

            # Step 5: Convert the downloaded file to .xlsx

            xlsx_file_path = os.path.join(downloads_folder, FileName + ".xlsx")            
            convert_xls_to_xlsx(new_file_path)

            file_processed = True
            
        except Exception as e:
            orchestrator_connection.log_error(f"An error occurred during Selenium operations: {str(e)}")
        finally:
            driver.quit()

        if log:
            orchestrator_connection.log_info("Getting file/folder")
        
        if file_processed:
            file_name = os.path.basename(xlsx_file_path)
            download_path = os.path.join(downloads_folder, file_name)

            if log:
                orchestrator_connection.log_info("Uploading file to sharepoint")

            if ":f:" in SharePointURL or ":r:" in SharePointURL:
                # Shared link resolution
                response = ctx.execute_request_direct({
                    "url": SharePointURL,
                    "method": "GET",
                    "headers": {
                        "Accept": "application/json;odata=verbose"
                    }
                })

                if response.status_code == 200:
                    resolved_data = response.json()
                    server_relative_url = resolved_data.get("d", {}).get("ServerRelativeUrl", None)
                    if not server_relative_url:
                        raise ValueError("Failed to resolve shared link to a server-relative URL.")
                    server_relative_url = server_relative_url.rstrip('/')
                    target_folder = ctx.web.get_folder_by_server_relative_url(server_relative_url)
                else:
                    raise ValueError(f"Failed to resolve shared link. Status code: {response.status_code}")
            else:
                # Standard URL resolution
                parsed_url = urlparse(SharePointURL)

                # Extract the `id` parameter that contains the folder path
                query_params = parse_qs(parsed_url.query)
                id_param = query_params.get("id", [None])[0]  # Extract the 'id' parameter value
                if not id_param:
                    raise ValueError("No 'id' parameter found in the URL.")
                decoded_path = unquote(id_param)  # Decode URL-encoded folder path

                # Validate the extracted path
                if not decoded_path.startswith(('/Teams')):
                    raise ValueError(f"Invalid decoded path extracted from URL: {decoded_path}")

                # Normalize the path to ensure it captures the full folder path
                decoded_path = decoded_path.rstrip('/')

                # Access the folder directly
                target_folder = ctx.web.get_folder_by_server_relative_url(decoded_path)

            # Upload the file
            if file_processed:
                with open(xlsx_file_path, "rb") as local_file:
                    file_content = local_file.read()
                    target_folder.upload_file(file_name, file_content).execute_query()

                print(f"File '{file_name}' uploaded successfully to {SharePointURL}")

            #Removing the local file
            if os.path.exists(xlsx_file_path):
                os.remove(xlsx_file_path)
            
            if os.path.exists(downloads_folder + "YKMD_STD.xls"):
                os.remove(download_path + "YKMD_STD.xls" )

