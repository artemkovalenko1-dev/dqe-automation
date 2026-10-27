import time
from pathlib import Path

import pandas as pd

from selenium import webdriver
from selenium.webdriver.chrome.webdriver import WebDriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    StaleElementReferenceException,
    WebDriverException,
)

BASE_DIR = Path(__file__).resolve().parent
REPORT_PATH = BASE_DIR / "report.html"
OUTPUT_DIR = BASE_DIR
TIMEOUT = 15

GRAPH_CLASS = "plotly-graph-div"
TABLE_CSS = "g.table"
PIE_SLICE_CSS = "g.pielayer g.slice"
# Plotly keeps empty g.slice nodes for hidden labels; only drawn slices have a surface path
VISIBLE_SLICE_CSS = "g.pielayer g.slice path.surface"
LEGEND_ITEM_CSS = "g.legend g.traces"

TABLE_CSV_NAME = "table.csv"
DOUGHNUT_COLUMNS = ["Facility Type", "Min Average Time Spent"]


class SeleniumWebDriverContextManager:
    def __init__(self, headless: bool = True, window_size: tuple = (1920, 1080)):
        self.headless = headless
        self.window_size = window_size
        self.driver = None

    def __enter__(self) -> WebDriver:
        options = webdriver.ChromeOptions()
        if self.headless:
            options.add_argument("--headless=new")
        options.add_argument(f"--window-size={self.window_size[0]},{self.window_size[1]}")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        self.driver = webdriver.Chrome(options=options)
        return self.driver

    def __exit__(self, exc_type, exc_value, traceback):
        if self.driver is not None:
            try:
                self.driver.quit()
            except WebDriverException as e:
                print(f"[WARN] Failed to quit WebDriver cleanly: {e}")
            finally:
                self.driver = None
        # Do not suppress exceptions raised inside the with-block
        return False


def _text(element) -> str:
    # textContent works for SVG nodes and for nodes clipped out of view, unlike .text
    return (element.get_attribute("textContent") or "").strip()


def _format_number(value) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    return str(int(number)) if number.is_integer() else str(number)


def wait_for_report(driver: WebDriver):
    """Locate the Plotly graph (CLASS_NAME -> ID) and wait until both traces are rendered."""
    wait = WebDriverWait(driver, TIMEOUT)
    graph = wait.until(EC.presence_of_element_located((By.CLASS_NAME, GRAPH_CLASS)))
    graph_id = graph.get_attribute("id")

    wait.until(lambda d: d.execute_script(
        "const gd = document.getElementById(arguments[0]);"
        "return !!(gd && gd._fullLayout && gd.querySelector('g.table') && gd.querySelector('g.pielayer'));",
        graph_id,
    ))
    return wait.until(EC.visibility_of_element_located((By.ID, graph_id)))


# ---------------------------------------------------------------- Table ---

def extract_table(driver: WebDriver, graph):
    table = WebDriverWait(graph, TIMEOUT).until(
        lambda g: g.find_element(By.CSS_SELECTOR, TABLE_CSS)
    )
    columns = table.find_elements(By.CSS_SELECTOR, "g.y-column")
    if not columns:
        raise NoSuchElementException("Table columns (g.y-column) not found")

    headers, dom_columns = [], []
    for column in columns:
        # SVG elements require local-name() in XPath
        header_el = column.find_element(
            By.XPATH, ".//*[local-name()='g' and @id='header']//*[local-name()='text']"
        )
        headers.append(_text(header_el))

        cell_els = column.find_elements(
            By.XPATH, ".//*[local-name()='g' and starts-with(@id,'cells')]//*[local-name()='text']"
        )
        dom_columns.append([t for t in (_text(c) for c in cell_els) if t])

    # Plotly virtualises table rows, so verify DOM content against the figure data
    source_columns = driver.execute_script(
        "const t = arguments[0].data.find(tr => tr.type === 'table');"
        "return t ? t.cells.values : null;",
        graph,
    )
    expected_rows = len(source_columns[0]) if source_columns else 0

    if dom_columns and all(len(col) == expected_rows for col in dom_columns):
        data_columns = dom_columns
    elif source_columns:
        print(f"[INFO] Only part of the table rows are rendered in DOM; using figure data ({expected_rows} rows).")
        data_columns = [[_format_number(v) if isinstance(v, (int, float)) else str(v) for v in col]
                        for col in source_columns]
    else:
        data_columns = dom_columns

    rows = list(zip(*data_columns))
    return headers, rows


def save_table(driver: WebDriver, graph) -> None:
    try:
        headers, rows = extract_table(driver, graph)
        output = OUTPUT_DIR / TABLE_CSV_NAME
        pd.DataFrame(rows, columns=headers).to_csv(output, index=False)
        print(f"[OK] Table saved to {output} ({len(rows)} rows)")
    except (TimeoutException, NoSuchElementException, StaleElementReferenceException) as e:
        print(f"[ERROR] Table not found or not loaded: {e}")
    except WebDriverException as e:
        print(f"[ERROR] WebDriver error while reading table: {e}")


# -------------------------------------------------------- Doughnut chart ---

def get_hidden_count(driver: WebDriver, graph) -> int:
    return driver.execute_script(
        "return (arguments[0]._fullLayout.hiddenlabels || []).length;", graph
    )


def get_source_doughnut_data(driver: WebDriver, graph):
    return driver.execute_script(
        """
        const gd = arguments[0];
        const idx = gd.data.findIndex(t => t.type === 'pie');
        if (idx < 0 || !gd.calcdata[idx]) return [];
        const hidden = (gd._fullLayout.hiddenlabels || []).map(String);
        return gd.calcdata[idx]
            .filter(p => p.label !== undefined && !p.hidden && !hidden.includes(String(p.label)))
            .map(p => [String(p.label), p.v]);
        """,
        graph,
    )


def extract_doughnut_data(driver: WebDriver, graph):
    dom_rows = []
    for slice_el in graph.find_elements(By.CSS_SELECTOR, PIE_SLICE_CSS):
        lines = [t for t in (_text(x) for x in
                 slice_el.find_elements(By.CSS_SELECTOR, "text.slicetext tspan.line")) if t]
        if len(lines) >= 2:
            dom_rows.append((lines[0], _format_number(lines[-1])))

    source_rows = [(label, _format_number(value)) for label, value in get_source_doughnut_data(driver, graph)]
    if len(dom_rows) != len(source_rows):
        print("[INFO] Slice labels not fully readable from DOM; using figure data.")
        return source_rows
    return dom_rows


def take_screenshot(driver: WebDriver, element, path: Path) -> None:
    try:
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
        if not element.screenshot(str(path)):
            raise WebDriverException("Element screenshot returned False")
    except WebDriverException as e:
        print(f"[WARN] Element screenshot failed ({e}); saving full page screenshot instead.")
        driver.save_screenshot(str(path))
    print(f"[OK] Screenshot saved to {path}")


def save_doughnut_csv(driver: WebDriver, graph, index: int) -> None:
    output = OUTPUT_DIR / f"doughnut{index}.csv"
    try:
        rows = extract_doughnut_data(driver, graph)
    except (NoSuchElementException, StaleElementReferenceException, WebDriverException) as e:
        print(f"[ERROR] Failed to read doughnut data for state {index}: {e}")
        rows = []
    # When all filters are unselected only the header is written
    pd.DataFrame(rows, columns=DOUGHNUT_COLUMNS).to_csv(output, index=False)
    print(f"[OK] Doughnut data saved to {output} ({len(rows)} rows)")


def wait_for_slices(driver: WebDriver, graph, expected_visible: int) -> None:
    WebDriverWait(driver, TIMEOUT).until(
        lambda d: len(graph.find_elements(By.CSS_SELECTOR, VISIBLE_SLICE_CSS)) == expected_visible
    )


def apply_filter(driver: WebDriver, graph, item_index: int, label: str) -> None:
    hidden_before = get_hidden_count(driver, graph)
    try:
        # Re-locate on every click: Plotly redraws the legend after each toggle
        item = graph.find_elements(By.CSS_SELECTOR, LEGEND_ITEM_CSS)[item_index]
        toggle = item.find_element(By.CSS_SELECTOR, "rect.legendtoggle")
        ActionChains(driver).move_to_element(toggle).click().perform()
        WebDriverWait(driver, TIMEOUT).until(
            lambda d: get_hidden_count(d, graph) == hidden_before + 1
        )
    except (IndexError, NoSuchElementException, StaleElementReferenceException,
            TimeoutException, WebDriverException) as e:
        print(f"[WARN] Legend click for '{label}' failed ({type(e).__name__}); applying filter via Plotly API.")
        driver.execute_script(
            """
            const gd = arguments[0], label = arguments[1];
            const hidden = (gd._fullLayout.hiddenlabels || []).slice();
            if (!hidden.includes(label)) hidden.push(label);
            return Plotly.relayout(gd, {hiddenlabels: hidden});
            """,
            graph, label,
        )
        WebDriverWait(driver, TIMEOUT).until(
            lambda d: get_hidden_count(d, graph) == hidden_before + 1
        )


def process_doughnut(driver: WebDriver, graph) -> None:
    try:
        WebDriverWait(graph, TIMEOUT).until(
            lambda g: g.find_elements(By.CSS_SELECTOR, PIE_SLICE_CSS)
        )
        legend_items = graph.find_elements(By.CSS_SELECTOR, LEGEND_ITEM_CSS)
        labels = [_text(i.find_element(By.CSS_SELECTOR, "text.legendtext")) for i in legend_items]
    except (TimeoutException, NoSuchElementException) as e:
        print(f"[ERROR] Doughnut chart or its legend not found: {e}")
        return

    total = len(labels)

    take_screenshot(driver, graph, OUTPUT_DIR / "screenshot0.png")
    save_doughnut_csv(driver, graph, 0)

    for step, label in enumerate(labels, start=1):
        try:
            # Plotly treats two clicks within 300 ms as a double click
            time.sleep(0.5)
            apply_filter(driver, graph, step - 1, label)
            wait_for_slices(driver, graph, total - step)
            print(f"[OK] Filter applied: '{label}' unselected ({total - step} slice(s) visible)")
        except (TimeoutException, WebDriverException) as e:
            print(f"[ERROR] Failed to apply filter '{label}': {e}")

        take_screenshot(driver, graph, OUTPUT_DIR / f"screenshot{step}.png")
        save_doughnut_csv(driver, graph, step)


def main() -> None:
    if not REPORT_PATH.exists():
        raise FileNotFoundError(f"Report not found: {REPORT_PATH}")

    with SeleniumWebDriverContextManager() as driver:
        driver.get(REPORT_PATH.as_uri())
        try:
            graph = wait_for_report(driver)
        except TimeoutException:
            print("[ERROR] Report did not load within the timeout.")
            return

        save_table(driver, graph)
        process_doughnut(driver, graph)


if __name__ == "__main__":
    main()
