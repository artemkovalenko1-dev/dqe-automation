*** Settings ***
Documentation     Verifies that the "Last week loaded data" table of the HTML report
...               exactly matches the facility_type_avg_time_spent_per_visit_date Parquet dataset.
Library           SeleniumLibrary
Library           OperatingSystem
Library           helper.py
Test Teardown     Close All Browsers


*** Variables ***
${REPORT_FILE}        ${CURDIR}${/}generated_report${/}report.html
${PARQUET_FOLDER}     ${CURDIR}${/}parquet_data${/}facility_type_avg_time_spent_per_visit_date
${FILTER_DATE}        2026-09-25
${BROWSER}            headlesschrome
${TABLE_LOCATOR}      css:div.plotly-graph-div g.table
${TIMEOUT}            15s
&{COLUMN_MAPPING}     facility_type=Facility Type    visit_date=Visit Date    avg_time_spent=Average Time Spent


*** Test Cases ***
HTML Report Table Should Match Parquet Dataset
    [Documentation]    Compares the report table with the Parquet data filtered from ${FILTER_DATE}.
    Open Report In Chrome    ${REPORT_FILE}
    ${table}=    Locate Report Table
    ${html_df}=    Read Html Table To Dataframe    ${table}
    Log    HTML table:\n${html_df}
    ${parquet_df}=    Read Parquet Dataset    ${PARQUET_FOLDER}    ${FILTER_DATE}
    ...    column_mapping=${COLUMN_MAPPING}
    Log    Parquet data:\n${parquet_df}
    ${match}    ${differences}=    Compare Dataframes    ${html_df}    ${parquet_df}
    IF    not ${match}    Fail    HTML report and Parquet dataset do not match:\n${differences}


*** Keywords ***
Open Report In Chrome
    [Arguments]    ${report_file}
    File Should Exist    ${report_file}
    ${url}=    Evaluate    pathlib.Path(r'''${report_file}''').resolve().as_uri()    modules=pathlib
    # Window size is set at startup: resizing later re-renders Plotly and makes elements stale
    Open Browser    ${url}    ${BROWSER}    options=add_argument("--window-size=1920,1080")

Locate Report Table
    Wait For Condition
    ...    const gd = document.querySelector('div.plotly-graph-div'); return !!(gd && gd._fullLayout && gd.querySelector('g.table'));
    ...    ${TIMEOUT}
    Wait Until Page Contains Element    ${TABLE_LOCATOR}    ${TIMEOUT}
    ${table}=    Get WebElement    ${TABLE_LOCATOR}
    RETURN    ${table}
