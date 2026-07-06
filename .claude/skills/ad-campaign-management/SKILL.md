---
name: ad-campaign-management
description: Methodology for analyzing and optimizing ad campaigns across Google Ads, Meta Ads, LinkedIn Ads, and TikTok Ads — performance thresholds, wasted-spend detection, campaign research, bidding, creative fatigue, PMax limits, reporting. Use when analyzing performance, researching before a campaign, optimizing budgets, or auditing ad accounts.
---

Methodology for managing advertising campaigns across Google Ads, Meta Ads, LinkedIn Ads, and TikTok Ads: how to analyze performance, detect wasted spend, research before launching, structure campaigns, and optimize budgets and creatives.

**IMPORTANT — no ad-platform tools are connected.** Tool names mentioned below (`get_campaign_performance`, `analyze_wasted_spend`, etc.) describe the *conceptual step* of each workflow, not callable tools. Get data from: (1) real campaign data provided in the prompt (e.g. the `CAMPAÑAS REALES DE META` block), (2) `WebSearch`/`WebFetch` for research, (3) clearly-labeled `[BENCHMARK]` estimates when no real data exists. Never pretend a tool call happened.

## When to Use This Skill

Activate when the user:

- Asks about ad campaign performance ("How are my Google Ads doing?")
- Wants to research keywords ("Find keywords for my plumbing business")
- Needs to create campaigns ("Launch a Google Search campaign for...")
- Wants budget optimization ("Where am I wasting ad spend?")
- Mentions advertising platforms (Google Ads, Meta, LinkedIn, TikTok)
- Asks about ad accounts or connections ("Which ad platforms are connected?")

## Required Workflow

**Follow these steps in order. Do not skip steps.**

### Step 1: Check Available Data

Always start here before any ad operation:

- Real campaign data in the prompt (e.g. `CAMPAÑAS REALES DE META`) → use it as-is, it is ground truth
- No real data → work with `[BENCHMARK]` estimates and say so explicitly

### Step 2: Apply the Workflow

No hay tools de plataformas conectadas en este entorno: trabajá con los datos reales inyectados en el prompt (p. ej. `CAMPAÑAS REALES DE META`) y con research web. Los nombres de tools que aparezcan más abajo son CONCEPTUALES: aplicá la metodología con los datos disponibles, nunca esperes ni inventes una tool call.


Follow the workflow patterns below with the data you have. Always analyze first (performance, status), then recommend (create, optimize).

### Step 3: Summarize and Recommend

Present results in tables with key metrics. Highlight top and underperforming items. Propose actionable next steps.

## Performance Analysis

- **Google Ads:** `get_campaign_performance` — params: `lookback_days` (7/30/60/90, default 30), optional `customer_id`
- **Meta Ads:** `get_meta_campaign_performance` — params: `lookback_days`, optional `ad_account_id`
- **LinkedIn Ads:** `get_linkedin_campaign_performance` — params: `lookback_days`
- **TikTok Ads:** `get_tiktok_campaign_performance` — params: `lookback_days`

Present: impressions, clicks, CTR, spend, conversions, cost/conversion, ROAS. Default to 30-day lookback.

## Cross-Platform Performance Dashboard

When the user asks for overall performance, a weekly review, or cross-platform comparison:

1. Call `get_connections_status` to identify active platforms
2. For each connected platform, pull performance:
   - Google: `get_campaign_performance`
   - LinkedIn: `get_linkedin_campaign_performance`
   - Meta: `get_meta_campaign_performance`
   - TikTok: `get_tiktok_campaign_performance`
3. For each platform, pull waste analysis:
   - Google: `analyze_wasted_spend`
   - LinkedIn: `analyze_linkedin_wasted_spend`
   - Meta: `analyze_meta_wasted_spend`
   - TikTok: `analyze_tiktok_wasted_spend`
4. Present a unified scorecard:

| Platform | Campaigns | Spend | CTR | CPA | ROAS | Waste | Health |
|----------|-----------|-------|-----|-----|------|-------|--------|
| Google   | ...       | ...   | ... | ... | ...  | ...   | ...    |
| LinkedIn | ...       | ...   | ... | ... | ...  | ...   | ...    |
| Meta     | ...       | ...   | ... | ... | ...  | ...   | ...    |
| TikTok   | ...       | ...   | ... | ... | ...  | ...   | ...    |
| **Total**| ...       | ...   |     |     |      | ...   |        |

5. Highlight:
   - Best performing platform and campaign
   - Worst performing platform and campaign
   - Total wasted spend and top waste sources
   - Budget pacing (on track, under, over)
6. Recommend top 3 actions across all platforms

## Campaign Research (run before creating ANY new campaign)

Before creating a campaign on any platform, research the brand's market position and competitive landscape. This combines web research (native tools) with whatever campaign data is available to inform every campaign decision — targeting, messaging, differentiation, and bidding.

### Step 0: Load Strategy Directives
Read STRATEGY.md — `## Active Directives` and skim `## Decision Log`. If directives exist, note them
as context that will inform (not skip) the research steps that follow. Directives shape
which competitors to focus on and what positioning angles to explore.

Do NOT skip Campaign Research just because directives exist. Directives may be stale,
incomplete, or based on exploratory conversations. Fresh research validates and enriches
them. However, avoid fully redundant research — if a comprehensive analysis was done
recently (check Decision Log dates), tell the user: "Strategy directives from [date]
are available. I'll use them as a starting point and validate with fresh data. Want me
to do a full re-analysis instead?"

### Step 1: Understand the brand's own website
Use `WebFetch` to crawl the brand's website. Extract:
- What they sell (products, services, pricing tiers)
- Key value propositions and differentiators
- Target audience language (how they describe their customers)
- Pricing (plans, tiers, free trial availability)
- Trust signals (customer logos, testimonials, case studies, awards)
- CTAs used on the site (what actions they push visitors toward)

### Step 2: Research the competitive landscape
Use `WebSearch` to search for:
- `"[brand's product category] competitors"` — find who they compete with
- `"[competitor name] vs [brand name]"` — find comparison content
- `"[competitor name] pricing"` — understand competitor price points
- `"best [product category] [current year]"` — find review/comparison sites

Then use `WebFetch` to crawl the top 3-5 competitor websites. Extract:
- Their positioning and messaging (how they describe themselves)
- Their pricing (cheaper? more expensive? different model?)
- Their unique claims (what do they say they do better?)
- Their target audience (who are they speaking to?)

### Step 3: Identify differentiation
Combine brand website + competitor research to answer:
- What does this brand do that competitors don't? (unique features, approach, pricing)
- What language resonates in this market? (common pain points, desired outcomes)
- Where are the gaps? (underserved audiences, unaddressed pain points)
- What should ad copy emphasize to stand out?

### Step 4: Review existing ad intelligence (if campaign data is available)
- `get_campaign_performance` — what's already running and how it performs
- `analyze_search_terms` — what real users search for (Google Ads)
- `get_campaign_structure` — current ad copy and targeting
- `get_benchmark_context` — industry benchmarks for this vertical

### Step 5: Create a research brief
Present findings to the user before proceeding with campaign creation:
- Market overview (key competitors, price ranges, positioning)
- Recommended differentiation angles (what to emphasize in ads)
- Suggested audiences based on competitive gaps
- Messaging direction (informed by competitor weaknesses and brand strengths)

Get user input on the direction before proceeding to keyword research and campaign creation.

## Bidding Strategy

**Before creating ANY Google Ads campaign, discuss bidding strategy with the user.**

1. Pull past performance: `get_campaign_performance` (lookback_days: 90)
2. Review existing strategies: `get_campaign_structure` to see what bidding strategies current campaigns use
3. Recommend a strategy based on data:

| Scenario | Recommended Strategy | Reasoning |
|----------|---------------------|-----------|
| New advertiser (no conversion data) | Maximize Clicks | Build traffic data first. Switch to Maximize Conversions after 30+ conversions. |
| Has conversion data (30+ conversions/month) | Maximize Conversions or Target CPA | Enough data for Smart Bidding to optimize. |
| Known target CPA | Target CPA | Set CPA at or slightly above historical average. |
| E-commerce with ROAS goals | Target ROAS | Set ROAS target based on margins and historical performance. |
| Brand campaign | Manual CPC or Maximize Clicks | Control spend on branded terms. Low CPCs expected. |
| High-value B2B leads | Target CPA | Long sales cycles need CPA control. Start 20% above current CPA, tighten over time. |

4. Present recommendation with reasoning to the user
5. Get explicit approval before setting the strategy
6. To change strategy on existing campaigns: `update_bid_strategy`

**Important:** Never silently pick a bidding strategy. Always explain the trade-offs and let the user decide.

## Budget Optimization (Google Ads)

- `optimize_budget_allocation` — suggest budget reallocations
- `analyze_wasted_spend` — find underperforming keywords and ad groups
- `analyze_search_terms` — review search terms for negative keyword opportunities

## Creative Fatigue Detection & Refresh

When reviewing creative performance or user asks about ad fatigue:

1. Meta: Call `detect_meta_creative_fatigue` for fatigue scores
2. LinkedIn: Call `analyze_linkedin_creative_performance` for per-creative metrics
3. Google: Call `get_campaign_structure` to see ad-level performance
4. Identify ads with:
   - High frequency + declining CTR (fatigued)
   - More than 30 days running with no refresh
   - Below-average CTR for their campaign
5. For fatigued ads:
   - Call `suggest_ad_content` for new headline/description ideas
   - Call `generate_linkedin_ad_creatives` for LinkedIn variations
   - Present new creative options (filtered through brand voice if CLAUDE.md exists)
   - On approval: update via `update_ad_headlines`, `update_ad_descriptions`, `add_linkedin_creative`, etc.

## A/B Testing Workflow

When creating new ad variations for testing:

1. Read current top-performing ad copy (from campaign structure)
2. Generate 3-5 variations testing ONE variable:
   - Headline variation (keep description same)
   - Description variation (keep headline same)
   - CTA variation
   - Audience variation (same ad, different targeting)
3. Present test plan with hypothesis:
   "Testing: 'Headline A' vs 'Headline B'
    Hypothesis: [why we think one may outperform]
    Duration: 2 weeks, split budget 50/50
    Success metric: CTR and conversion rate"
4. On approval, create test variants via platform-specific tools
5. Log test for follow-up analysis

## Audience Analysis & Optimization

When analyzing or optimizing audiences:

1. Pull audience data:
   - Meta: `get_meta_audience_insights` + `analyze_meta_audiences`
   - LinkedIn: `get_linkedin_audience_insights`
   - Google: Review campaign targeting from `get_campaign_structure`
2. Identify:
   - Which audience segments convert best (by age, gender, job title, interest)
   - Audience overlap/saturation
   - Underperforming segments (high spend, low conversion)
3. For LinkedIn B2B specifically:
   - Call `research_business_for_linkedin_targeting` with brand's website
   - Compare AI-recommended targeting vs current targeting
   - Identify gaps (seniority levels, industries, company sizes not covered)
4. For Meta:
   - Call `optimize_meta_placements` for placement-level performance
   - Identify which placements to scale/reduce
5. Present findings with recommendations:
   - Segments to expand (high ROAS, low spend)
   - Segments to cut (low ROAS, high spend)
   - New segments to test

## Competitive Intelligence

When analyzing competitors or adjusting competitive strategy:

### Step 1: Identify competitors
- Read CLAUDE.md for known competitors (check Competitors section)
- Use `WebSearch` to search `"[brand product category] competitors [current year]"` and `"[brand name] alternatives"`
- Use `WebSearch` to find review/comparison sites: `"best [product category] [current year]"`

### Step 2: Research competitor positioning
For each key competitor (top 3-5):
- Use `WebFetch` to crawl their website homepage — extract messaging, value props, positioning
- Use `WebFetch` to crawl their pricing page — extract plans, pricing model, free tier
- Use `WebSearch` to search `"[competitor] ads"` or `"[competitor] Google Ads"` — find their ad copy if visible
- Use `WebFetch` to crawl competitor landing pages found in search results — analyze their conversion approach

### Step 3: Analyze ad platform data
- `analyze_search_terms` — find competitor brand terms appearing in our search queries
- `research_keywords` — get search volume and CPC for competitor brand + product terms
- `get_campaign_structure` — check if we already bid on competitor terms

### Step 4: Assess competitive position
- Are competitors bidding on our brand terms? (defensive strategy needed)
- Which competitor keywords have high volume + reasonable CPC?
- Where do we differentiate? (pricing, features, audience, positioning)
- What messaging do competitors use that we should counter or avoid?
- Are there underserved niches competitors ignore?

### Step 5: Recommend actions
- **Brand defense campaigns**: exact match on own brand terms (if competitors are bidding on them)
- **Competitor conquest campaigns**: bid on competitor brand terms with ad copy emphasizing our differentiators
- **Differentiation messaging**: specific claims based on competitive gaps (e.g., "50% cheaper than [competitor]", "No setup fee unlike [competitor]")
- **Negative keywords**: exclude competitor terms where intent doesn't match (e.g., "[competitor] login" — existing customers, not prospects)
- Update CLAUDE.md Competitors section with findings

## Safety Rules

These tools create REAL campaigns that spend REAL money.

1. **Always confirm with the user** before creating campaigns or changing spend
2. **Never retry campaign creation automatically** on error
3. **Never modify live budgets** without explicit user approval
4. All campaigns created in **PAUSED status** when possible
5. When in doubt about any spend-affecting action, **ask the user first**

## Platform Guidance

| Platform | Min Daily | Recommended | Best for |
|----------|-----------|-------------|----------|
| Google Ads Search | $10 | $50+ | High-intent search traffic |
| Google Ads PMax | $10 | $50+ | Broad reach with automation across Search, Display, YouTube, Gmail, Discover |
| Google Ads Display | $5 | $20+ | Image / responsive display ads across the Google Display Network |
| Google Ads Demand Gen | $10 | $20+ | YouTube, Gmail, Discover — visual awareness + consideration |
| Google Ads YouTube | $10 | $20+ | YouTube-only video ads (In-Feed, In-Stream, Shorts) |
| Meta Ads | $5/ad set | $20+ | Image, video, carousel, OUTCOME_LEADS — awareness, retargeting, lead gen |
| LinkedIn Ads | $10 | $50+ | B2B targeting (job titles, industries); image, video, carousel, lead-gen |
| TikTok Ads | $20 | $50+ | In-feed video, Spark Ads (boost organic), Carousel, App Promotion |

## Output Formatting

- **Performance:** Table with impressions, clicks, CTR, spend, conversions, CPC, ROAS. Order by spend descending.
- **Keywords:** Group by intent, show search volume and CPC ranges.
- **Campaign creation:** Confirm all settings with user before execution, show campaign ID after.
- **Cross-platform:** Side-by-side comparison table.
- **Errors:** Report full error message. Never retry creation tools automatically.

