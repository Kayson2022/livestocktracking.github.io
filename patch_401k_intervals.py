#!/usr/bin/env python3
"""
Adds separate, user-editable auto-refresh intervals for pre-market and
after-hours to the 401k app.

Before: one editable interval for regular hours, everything else hardcoded
to 300 seconds. Waking up at 6am meant a 5-minute refresh even though
pre-market was already trading.

After: three editable fields. Overnight and weekends stay at 300.

Usage:
    python3 patch_401k_intervals.py --check   # verify, change nothing
    python3 patch_401k_intervals.py           # apply (writes a .bak first)
"""
import sys
import shutil
from datetime import datetime

TARGET = '401k_app-08-31-2026.html'

# ── 1. Storage keys ────────────────────────────────────────────────────
KEYS_ANCHOR = "        const REFRESH_INTERVAL_KEY = 'myPortfolioRefreshInterval_v4';"
KEYS_NEW = KEYS_ANCHOR + """
        const PREMARKET_INTERVAL_KEY  = 'myPortfolioPreMarketInterval_v1';
        const AFTERHOURS_INTERVAL_KEY = 'myPortfolioAfterHoursInterval_v1';"""

# ── 2. Module-level defaults ───────────────────────────────────────────
VAR_ANCHOR = "        let autoRefreshIntervalSeconds = 300;"
VAR_NEW = """        let autoRefreshIntervalSeconds = 300;
        // Pre-market and after-hours default to 120s: those sessions move
        // less than the regular session, so refreshing as fast as 72s spends
        // API quota without showing much new.
        let preMarketIntervalSeconds  = 120;
        let afterHoursIntervalSeconds = 120;"""

# ── 3. Loader ──────────────────────────────────────────────────────────
LOAD_ANCHOR = """        function loadAutoRefreshInterval() {
            const storedInterval = localStorage.getItem(REFRESH_INTERVAL_KEY);
            autoRefreshIntervalSeconds = storedInterval ? parseInt(storedInterval, 10) : 300;
        }"""
LOAD_NEW = """        function loadAutoRefreshInterval() {
            const storedInterval = localStorage.getItem(REFRESH_INTERVAL_KEY);
            autoRefreshIntervalSeconds = storedInterval ? parseInt(storedInterval, 10) : 300;
            const pre  = localStorage.getItem(PREMARKET_INTERVAL_KEY);
            const post = localStorage.getItem(AFTERHOURS_INTERVAL_KEY);
            preMarketIntervalSeconds  = pre  ? parseInt(pre, 10)  : 120;
            afterHoursIntervalSeconds = post ? parseInt(post, 10) : 120;
        }

        // Single source of truth for how often to refresh, in ET minutes:
        //   04:00-09:30 pre-market, 09:30-16:00 regular, 16:00-20:00 after-hours.
        // Outside those windows nothing trades, so 300s is plenty.
        function intervalForNow() {
            const et  = new Date(new Date().toLocaleString('en-US', {timeZone: 'America/New_York'}));
            const day = et.getDay();
            if (day === 0 || day === 6) return 300;
            const t = et.getHours() * 60 + et.getMinutes();
            if (t >= 570 && t < 960)  return autoRefreshIntervalSeconds;
            if (t >= 240 && t < 570)  return preMarketIntervalSeconds;
            if (t >= 960 && t < 1200) return afterHoursIntervalSeconds;
            return 300;
        }"""

# ── 4. Both smart-interval helpers now delegate ────────────────────────
SMART1_ANCHOR = """                    function getSmartIntervalFB() {
                        const now = new Date();
                        const et  = new Date(now.toLocaleString('en-US', {timeZone: 'America/New_York'}));
                        const day = et.getDay();
                        const t   = et.getHours() * 60 + et.getMinutes();
                        const isWeekend    = day === 0 || day === 6;
                        const isMarketOpen = !isWeekend && t >= 570 && t < 960;
                        return isMarketOpen ? autoRefreshIntervalSeconds : 300;
                    }"""
SMART1_NEW = """                    function getSmartIntervalFB() { return intervalForNow(); }"""

SMART2_ANCHOR = """            function getSmartInterval() {
                const now = new Date();
                const et  = new Date(now.toLocaleString('en-US', {timeZone: 'America/New_York'}));
                const day = et.getDay(); // 0=Sun 6=Sat
                const h   = et.getHours();
                const m   = et.getMinutes();
                const t   = h * 60 + m;
                const isWeekend    = day === 0 || day === 6;
                const isMarketOpen = !isWeekend && t >= 570 && t < 960; // 9:30-16:00
                if (isMarketOpen) return autoRefreshIntervalSeconds;
                return 300; // 5 minutes after hours / weekends
            }"""
SMART2_NEW = """            function getSmartInterval() { return intervalForNow(); }"""

# ── 5. Settings form fields ────────────────────────────────────────────
FORM_ANCHOR = """            <div class="form-group">
                <label for="autoRefreshIntervalInput">Auto-Refresh Interval (seconds)</label>
                <input type="number" id="autoRefreshIntervalInput" step="1" min="30" placeholder="e.g., 75">
                <small>Minimum 30 seconds to respect API limits.</small>
            </div>"""
FORM_NEW = """            <div class="form-group">
                <label for="autoRefreshIntervalInput">Auto-Refresh &mdash; Regular Hours (seconds)</label>
                <input type="number" id="autoRefreshIntervalInput" step="1" min="30" placeholder="e.g., 72">
                <small>9:30 AM &ndash; 4:00 PM ET. Minimum 30 seconds to respect API limits.</small>
            </div>
            <div class="form-group">
                <label for="preMarketIntervalInput">Auto-Refresh &mdash; Pre-Market (seconds)</label>
                <input type="number" id="preMarketIntervalInput" step="1" min="30" placeholder="e.g., 120">
                <small>4:00 &ndash; 9:30 AM ET (1:00 &ndash; 6:30 AM Pacific).</small>
            </div>
            <div class="form-group">
                <label for="afterHoursIntervalInput">Auto-Refresh &mdash; After-Hours (seconds)</label>
                <input type="number" id="afterHoursIntervalInput" step="1" min="30" placeholder="e.g., 120">
                <small>4:00 &ndash; 8:00 PM ET (1:00 &ndash; 5:00 PM Pacific). Overnight and weekends stay at 300s.</small>
            </div>"""

# ── 6. Save handler ────────────────────────────────────────────────────
SAVE_ANCHOR = """            let newInterval = parseInt(document.getElementById('autoRefreshIntervalInput').value.trim(), 10);

            if (isNaN(newInterval) || newInterval < 30) {
                showConfirmationModal("Invalid interval. Please enter a number that is 30 or greater.", null);
                return;
            }
            autoRefreshIntervalSeconds = newInterval;"""
SAVE_NEW = """            let newInterval = parseInt(document.getElementById('autoRefreshIntervalInput').value.trim(), 10);

            if (isNaN(newInterval) || newInterval < 30) {
                showConfirmationModal("Invalid interval. Please enter a number that is 30 or greater.", null);
                return;
            }
            // Blank pre/after-hours fields keep the current value rather than
            // resetting to a default, so clearing a box is never destructive.
            const _preRaw  = document.getElementById('preMarketIntervalInput').value.trim();
            const _postRaw = document.getElementById('afterHoursIntervalInput').value.trim();
            const _pre  = _preRaw  === '' ? preMarketIntervalSeconds  : parseInt(_preRaw, 10);
            const _post = _postRaw === '' ? afterHoursIntervalSeconds : parseInt(_postRaw, 10);
            if (isNaN(_pre) || _pre < 30 || isNaN(_post) || _post < 30) {
                showConfirmationModal("Pre-market and after-hours intervals must be 30 or greater.", null);
                return;
            }
            autoRefreshIntervalSeconds = newInterval;
            preMarketIntervalSeconds  = _pre;
            afterHoursIntervalSeconds = _post;
            localStorage.setItem(PREMARKET_INTERVAL_KEY,  preMarketIntervalSeconds);
            localStorage.setItem(AFTERHOURS_INTERVAL_KEY, afterHoursIntervalSeconds);"""

# ── 7. Populate fields when Settings opens ─────────────────────────────
POP_ANCHOR = "            document.getElementById('autoRefreshIntervalInput').value = autoRefreshIntervalSeconds;"
POP_NEW = """            document.getElementById('autoRefreshIntervalInput').value = autoRefreshIntervalSeconds;
            const _preEl  = document.getElementById('preMarketIntervalInput');
            const _postEl = document.getElementById('afterHoursIntervalInput');
            if (_preEl)  _preEl.value  = preMarketIntervalSeconds;
            if (_postEl) _postEl.value = afterHoursIntervalSeconds;"""

PATCHES = [
    ('storage keys',   KEYS_ANCHOR,   KEYS_NEW),
    ('defaults',       VAR_ANCHOR,    VAR_NEW),
    ('loader',         LOAD_ANCHOR,   LOAD_NEW),
    ('getSmartIntervalFB', SMART1_ANCHOR, SMART1_NEW),
    ('getSmartInterval',   SMART2_ANCHOR, SMART2_NEW),
    ('settings form',  FORM_ANCHOR,   FORM_NEW),
    ('save handler',   SAVE_ANCHOR,   SAVE_NEW),
    ('populate form',  POP_ANCHOR,    POP_NEW),
]


def main():
    check_only = '--check' in sys.argv
    path = TARGET
    for a in sys.argv[1:]:
        if not a.startswith('--'):
            path = a

    try:
        with open(path, encoding='utf-8') as f:
            src = f.read()
    except FileNotFoundError:
        print('File not found: ' + path)
        print('Pass the path as an argument if it is not in this folder.')
        return 1

    if 'PREMARKET_INTERVAL_KEY' in src:
        print('Already patched — nothing to do.')
        return 0

    bad = []
    for name, anchor, _ in PATCHES:
        n = src.count(anchor)
        print('  %-22s %s' % (name, 'OK' if n == 1 else 'FOUND %dx' % n))
        if n != 1:
            bad.append(name)

    if bad:
        print('\nAborted — these anchors are not unique: ' + ', '.join(bad))
        return 1

    if check_only:
        print('\nCheck passed. Run again without --check to apply.')
        return 0

    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup = path + '.bak_' + stamp
    shutil.copy2(path, backup)
    print('\nBackup: ' + backup)

    for _, anchor, new in PATCHES:
        src = src.replace(anchor, new, 1)

    with open(path, 'w', encoding='utf-8') as f:
        f.write(src)

    print('Patched ' + path)
    print('Upload it, then open Settings — three interval fields should appear.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
