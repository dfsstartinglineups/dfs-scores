import streamlit as st
import requests
import pandas as pd
import time

# ==========================================
# 1. CONFIGURATION & PAGE SETUP
# ==========================================
st.set_page_config(page_title="DFS Scores", layout="wide")
st.title("🏀 DFS Scores: NBA Real-Time Tracker")
st.markdown("Fetch real-time stats, Fanduel, and DraftKings scores for today's games.")

# Input: Date Picker (Defaults to today)
target_date_obj = st.date_input("Select Date", pd.to_datetime("today"))
TARGET_DATE = target_date_obj.strftime("%Y%m%d")

# ==========================================
# 2. SCORING FUNCTIONS
# ==========================================
def calculate_draftkings(pts, three_pm, reb, ast, stl, blk, to):
    """
    DraftKings Scoring:
    PTS=1, 3PM=0.5, REB=1.25, AST=1.5, STL=2, BLK=2, TO=-0.5
    Double-Double Bonus=+1.5, Triple-Double Bonus=+3
    """
    score = pts + (three_pm * 0.5) + (reb * 1.25) + (ast * 1.5) + (stl * 2) + (blk * 2) - (to * 0.5)
    
    # Check Bonuses
    categories_over_10 = 0
    if pts >= 10: categories_over_10 += 1
    if reb >= 10: categories_over_10 += 1
    if ast >= 10: categories_over_10 += 1
    if stl >= 10: categories_over_10 += 1
    if blk >= 10: categories_over_10 += 1
    
    if categories_over_10 >= 3:
        score += 3 # Triple Double
    elif categories_over_10 >= 2:
        score += 1.5 # Double Double
        
    return round(score, 2)

def calculate_fanduel(pts, reb, ast, stl, blk, to):
    """
    FanDuel Scoring:
    PTS=1, REB=1.2, AST=1.5, STL=3, BLK=3, TO=-1
    """
    return round(pts + (reb * 1.2) + (ast * 1.5) + (stl * 3) + (blk * 3) - to, 2)

# ==========================================
# 3. DATA FETCHING FUNCTIONS
# ==========================================

@st.cache_data(ttl=60) # Cache data for 60 seconds to prevent spamming API on refresh
def get_nba_data(date_str):
    """Fetches games and player stats for the given date."""
    
    # 1. Get Game IDs
    url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={date_str}&limit=100"
    try:
        resp = requests.get(url)
        data = resp.json()
        games = []
        for event in data.get('events', []):
            game_id = event['id']
            name = event['name']
            status = event['status']['type']['state']
            games.append((game_id, name, status))
    except Exception as e:
        st.error(f"Error fetching scoreboard: {e}")
        return []

    if not games:
        return []

    all_player_stats = []
    
    # Progress Bar
    progress_bar = st.progress(0)
    total_games = len(games)

    # 2. Loop through games
    for i, (gid, game_name, status) in enumerate(games):
        # Update progress
        progress_bar.progress((i + 1) / total_games)
        
        summary_url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event={gid}"
        try:
            resp = requests.get(summary_url)
            data = resp.json()
            
            if 'boxscore' not in data or 'players' not in data['boxscore']:
                continue

            teams = data['boxscore']['players']

            for team in teams:
                team_name = team.get('team', {}).get('displayName', 'Unknown')
                if not team.get('statistics'): continue

                stats_block = team['statistics'][0]
                labels = stats_block['labels']
                athletes = stats_block['athletes']

                # Dynamic Index Mapping
                try:
                    idx_pts = labels.index('PTS')
                    idx_reb = labels.index('REB')
                    idx_ast = labels.index('AST')
                    idx_stl = labels.index('STL')
                    idx_blk = labels.index('BLK')
                    idx_to  = labels.index('TO')
                    # 3PT is usually formatted as "M-A" (Made-Attempted)
                    idx_3pt = labels.index('3PT') 
                except ValueError:
                    continue 

                for entry in athletes:
                    ath = entry['athlete']
                    stats_vals = entry['stats']
                    
                    # Basic Validation
                    if not stats_vals or len(stats_vals) < len(labels): continue
                    
                    try:
                        name = ath.get('displayName', 'Unknown')
                        pos = ath.get('position', {}).get('abbreviation', 'N/A')
                        
                        # Helper to parse integers safely
                        def parse_stat(val):
                            return int(val) if val.isdigit() else 0
                        
                        # Helper to parse "Made-Attempted" strings (e.g. "3-7")
                        def parse_shooting(val):
                            if '-' in val:
                                return int(val.split('-')[0])
                            return int(val) if val.isdigit() else 0

                        pts = parse_stat(stats_vals[idx_pts])
                        reb = parse_stat(stats_vals[idx_reb])
                        ast = parse_stat(stats_vals[idx_ast])
                        stl = parse_stat(stats_vals[idx_stl])
                        blk = parse_stat(stats_vals[idx_blk])
                        to  = parse_stat(stats_vals[idx_to])
                        three_pm = parse_shooting(stats_vals[idx_3pt])

                        fd_score = calculate_fanduel(pts, reb, ast, stl, blk, to)
                        dk_score = calculate_draftkings(pts, three_pm, reb, ast, stl, blk, to)

                        all_player_stats.append({
                            'Player': name,
                            'Pos': pos,
                            'Team': team_name,
                            'PTS': pts,
                            'REB': reb,
                            'AST': ast,
                            'STL': stl,
                            'BLK': blk,
                            '3PM': three_pm,
                            'TO': to,
                            'FanDuel': fd_score,
                            'DraftKings': dk_score
                        })
                    except Exception as e:
                        continue 
                        
        except Exception as e:
            print(f"Error scraping game {gid}: {e}")
        
        time.sleep(0.1) # Slight delay to be nice to API
        
    return all_player_stats

# ==========================================
# 4. MAIN APP LOGIC
# ==========================================

if st.button("🚀 Fetch Stats"):
    with st.spinner(f"Scraping data for {TARGET_DATE}..."):
        data = get_nba_data(TARGET_DATE)
        
    if data:
        df = pd.DataFrame(data)

        # 1. Sort by FanDuel Score (High to Low)
        df = df.sort_values(by='FanDuel', ascending=False)
        
        # Display Summary Metrics
        col1, col2, col3 = st.columns(3)
        col1.metric("Total Players", len(df))
        col2.metric("Top FD Score", df['FanDuel'].max())
        col3.metric("Top DK Score", df['DraftKings'].max())
        
        # Tabs for different views
        tab1, tab2 = st.tabs(["📋 Main Table", "📊 Top Performers"])
        
        with tab1:
            st.write("### Full Player List (Sorted by FanDuel)")
            
            # --- DYNAMIC HEIGHT CALCULATION ---
            # (Rows + 1 for header) * 35px per row + 3px buffer
            table_height = (len(df) + 1) * 35 + 3
            
            st.dataframe(
                df.style.format({"FanDuel": "{:.2f}", "DraftKings": "{:.2f}"})
                  .background_gradient(subset=['FanDuel', 'DraftKings'], cmap="Greens"),
                use_container_width=True,
                height=table_height  # <--- This sets the height to fit everyone!
            )
            
            # Download Button
            csv = df.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📥 Download CSV",
                data=csv,
                file_name=f"dfs_scores_{TARGET_DATE}.csv",
                mime="text/csv",
            )
            
        with tab2:
            st.subheader("Top 10 FanDuel")
            # We use .head(10) here specifically for the 'Top 10' view
            st.table(df.sort_values(by='FanDuel', ascending=False).head(10)[['Player', 'Pos', 'FanDuel', 'PTS', 'REB', 'AST']])
            
            st.subheader("Top 10 DraftKings")
            st.table(df.sort_values(by='DraftKings', ascending=False).head(10)[['Player', 'Pos', 'DraftKings', 'PTS', '3PM', 'REB', 'AST']])
            
    else:
        st.warning("No data found. Games may not have started yet or the date is incorrect.")

