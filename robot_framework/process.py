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
import gc
import subprocess



def process(orchestrator_connection: OrchestratorConnection, queue_element: QueueElement | None = None) -> None:
   
    # Global variables for ensuring single execution
    conversion_in_progress = set()

    def convert_xls_to_xlsx(path: str) -> None:
        """
        Converts an .xls file to .xlsx format. Times out if the process exceeds the given duration.
        
        Args:
            path (str): Path to the .xls file.
            timeout (int): Maximum time allowed for conversion (in seconds).
        """
        absolute_path = os.path.abspath(path)
        if absolute_path in conversion_in_progress:
            orchestrator_connection.log_info(f"Conversion already in progress for {absolute_path}. Skipping.")
            return
        
        conversion_in_progress.add(absolute_path)
        try:
            orchestrator_connection.log_info(f'Absolute path {absolute_path} found')
            excel = win32.gencache.EnsureDispatch('Excel.Application')
            wb = excel.Workbooks.Open(absolute_path)

            # FileFormat=51 is for .xlsx extension
            new_path = os.path.splitext(absolute_path)[0] + ".xlsx"
            wb.SaveAs(new_path, FileFormat=51)
            wb.Close()
            excel.Application.Quit()
            del wb
            del excel
        except Exception as e:
            orchestrator_connection.log_error(f"An unexpected error occurred: {e}")
            raise e
        finally:
            conversion_in_progress.remove(absolute_path)
    orchestrator_connection.log_info("Started process")

    # Opus bruger
    OpusLogin = orchestrator_connection.get_credential("OpusBruger")
    OpusUser = OpusLogin.username
    OpusPassword = OpusLogin.password 

    # Robotpassword
    RobotCredential = orchestrator_connection.get_credential("Robot365User") 
    RobotUsername = RobotCredential.username
    RobotPassword = RobotCredential.password

    # Define the queue name
    queue_name = "OpusBookmarkQueue" 

    # Get all queue elements with status 'New'
    queue_item = orchestrator_connection.get_next_queue_element(queue_name)
    if not queue_item:
        orchestrator_connection.log_info("No new queue items to process.")
        exit()

    specific_content = json.loads(queue_item.data)

    orchestrator_connection.log_info("Assigning variables")

    # Assign variables from SpecificContent
    BookmarkID = specific_content.get("Bookmark")
    OpusBookmark = orchestrator_connection.get_constant("OpusBookMarkUrl").value + BookmarkID
    SharePointURL = orchestrator_connection.get_constant("LauraTestSharepointURLFullPath").value
    #SharepointURL = specific_content.get("SharePointMappeLink", None)
    FileName = specific_content.get("Filnavn", None)
    Daily = specific_content.get("Dagligt (Ja/Nej)", None)
    MonthEnd = specific_content.get("MånedsSlut (Ja/Nej)", None)
    MonthStart = specific_content.get("MånedsStart (Ja/Nej)", None)
    Yearly = specific_content.get("Årligt (Ja/Nej)", None)
    print(FileName)
    orchestrator_connection.log_info(FileName)

        # Mark the queue item as 'In Progress'
    orchestrator_connection.set_queue_element_status(queue_item.id, "IN_PROGRESS")

    # Mark the queue item as 'Done' after processing
    orchestrator_connection.set_queue_element_status(queue_item.id, "DONE")

    Run = False
    xlsx_file_path_check = False

    # Testing if it should run
    if Daily.lower() == "ja":
        Run = True
    else:
        current_date = datetime.now()
        year, month, day = current_date.year, current_date.month, current_date.day
        last_day_of_month = calendar.monthrange(year, month)[1]  
        if MonthEnd.lower() == "ja" and day == last_day_of_month:
            Run = True
        elif MonthStart.lower() == "ja" and day == 1:
            Run = True
        elif Yearly.lower() == "ja" and day == 31 and month == 12:
            Run = True

    if Run:
        orchestrator_connection.log_info("Connecting to sharepoint")
        SharepointURL_connection = SharePointURL.split("/Delte")[0]

        credentials = UserCredential(RobotUsername, RobotPassword)
        ctx = ClientContext(SharepointURL_connection).with_credentials(credentials)

        web = ctx.web
        ctx.load(web)
        ctx.execute_query()

        downloads_folder = os.path.join(os.path.expanduser("~"), "Downloads")
        file_path = os.path.join(downloads_folder, FileName + ".xls")

        if os.path.exists(file_path):
            os.remove(file_path)
            print('File removed')

        chrome_options = Options()
        chrome_options.add_experimental_option("prefs", {
            "download.default_directory": downloads_folder,
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
        })
        chrome_options.add_argument("--disable-search-engine-choice-screen")

        chrome_service = Service()
        driver = webdriver.Chrome(service=chrome_service, options=chrome_options)
        
        try:
            orchestrator_connection.log_info("Navigating to Opus login page")
            driver.get(orchestrator_connection.get_constant("OpusAdgangUrl").value)
            WebDriverWait(driver, 60).until(EC.presence_of_element_located((By.ID, "logonuidfield")))
            
            driver.find_element(By.ID, "logonuidfield").send_keys(OpusUser)
            driver.find_element(By.ID, "logonpassfield").send_keys(OpusPassword)
            driver.find_element(By.ID, "buttonLogon").click()
            
            orchestrator_connection.log_info("Logged in to Opus portal successfully")
            driver.get(OpusBookmark)
            orchestrator_connection.log_info("Driver got bookmark")
            WebDriverWait(driver, timeout = 60*15).until(EC.frame_to_be_available_and_switch_to_it((By.CSS_SELECTOR, "iframe[id^='iframe_Roundtrip']")))

            WebDriverWait(driver, timeout = 60*15).until(EC.presence_of_element_located((By.ID, "BUTTON_EXPORT_btn1_acButton")))
            driver.find_element(By.ID, "BUTTON_EXPORT_btn1_acButton").click()

            orchestrator_connection.log_info("Waiting for file download to complete")
            time.sleep(2)

            initial_file_count = len(os.listdir(downloads_folder))
            start_time = time.time()
            while True:
                files = os.listdir(downloads_folder)
                if len(files) > initial_file_count:
                    latest_file = max(
                        [os.path.join(downloads_folder, f) for f in files], key=os.path.getctime
                    )
                    if latest_file.endswith(".xls"):
                        orchestrator_connection.log_info('Found xls file')
                        new_file_path = os.path.join(downloads_folder, f"{FileName}.xls")
                        os.rename(latest_file, new_file_path)
                        orchestrator_connection.log_info(f"File downloaded and renamed to {new_file_path}")
                        xlsx_file_path_check = True
                        break
                    
                if time.time() - start_time > 1800:
                    raise TimeoutError("File download did not complete within 30 minutes.")
                    
                time.sleep(1)
            if xlsx_file_path_check == True:
                xlsx_file_path = os.path.join(downloads_folder, FileName + ".xlsx")
                try:
                    orchestrator_connection.log_info(f'Converting {new_file_path}')
                    convert_xls_to_xlsx(new_file_path)
                    orchestrator_connection.log_info("File converted successfully")
            
                except Exception as e:
                    gc.collect()
                    subprocess.call("taskkill /im excel.exe /f >nul 2>&1", shell=True)
                    time.sleep(2)
                    if os.path.exists(xlsx_file_path):
                        os.remove(xlsx_file_path)
                    orchestrator_connection.log_error(str(e))
                    raise e

        except Exception as e:
            orchestrator_connection.log_error(f"An error occurred: {e}")
            print(f"An error occurred: {e}")
        finally:
            driver.quit()
    print(str(xlsx_file_path_check) + "Check")
    if xlsx_file_path_check == True:
        file_name = os.path.basename(xlsx_file_path)
        download_path = os.path.join(downloads_folder, file_name)

        orchestrator_connection.log_info("Uploading file to sharepoint")

        parsed_url = urlparse(SharePointURL)
        query_params = parse_qs(parsed_url.query)
        id_param = query_params.get("id", [None])[0]
        if not id_param:
            raise ValueError("No 'id' parameter found in the URL.")
        decoded_path = unquote(id_param)
        decoded_path = decoded_path.rstrip('/')
        target_folder = ctx.web.get_folder_by_server_relative_url(decoded_path)

        with open(xlsx_file_path, "rb") as local_file:
            target_folder.upload_file(file_name, local_file.read()).execute_query()
            print(f"File '{file_name}' uploaded successfully to {SharePointURL}")
            
        if os.path.exists(xlsx_file_path):
            os.remove(xlsx_file_path)
    else:
        print("An error occured - file was not processed correctly")
        orchestrator_connection.log_error("An error occured - file was not processed correctly")

    #Deleting potential leftover files from downloads folder
    orchestrator_connection.log_info('Deleting local files')
    if os.path.exists(downloads_folder + '\\' + FileName + ".xls"):
        os.remove(downloads_folder + '\\' +  FileName + ".xls")
    if os.path.exists("YKMD_STD.xls"):
        os.remove("YKMD_STD.xls")

