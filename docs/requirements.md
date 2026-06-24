# Grimsby-London Rail Simulation Requirements

## 1. Purpose

This project will explore whether improvements to Grimsby-London rail connectivity are practical, with an initial focus on the Grimsby-Doncaster and Doncaster-Grimsby corridor.

The application should simulate existing rail services, disruption scenarios, and future service options so that potential benefits and operational issues can be shown clearly.

## 2. Project Goals

- Model the current Grimsby-Doncaster and Doncaster-Grimsby service pattern.
- Include relevant interacting services, starting with Northern's Scunthorpe-Lincoln route where it affects the corridor.
- Allow delays, cancellations, and additional rail traffic to be simulated.
- Identify conflicts, delay propagation, and reliability issues.
- Provide a Streamlit GUI for scenario setup, simulation results, and visual analysis.
- Leave scope to test a future direct Grimsby-London service path.

## 3. Users

The primary users are:

- Project author or analyst exploring route feasibility.
- Stakeholders who need a clear visual explanation of service constraints.
- Non-technical viewers who need understandable outputs rather than raw railway data.

## 4. Initial Scope

The MVP should cover:

- Grimsby Town to Doncaster services.
- Doncaster to Grimsby Town services.
- Basic station stopping patterns.
- Scheduled arrival and departure times.
- Manual delay input.
- Manual service cancellation.
- Basic metrics for delay and service reliability.
- Streamlit pages or sections for inputs, timetable view, results, and summary metrics.

The MVP does not need to model every railway operational detail. It should provide a clear and expandable simulation foundation.

## 5. Out Of Scope For MVP

The first version does not need:

- Real-time railway data feeds.
- Full national timetable integration.
- Signalling block-level modelling.
- Exact platform occupation modelling at every station.
- Automated timetable planning.
- Revenue or demand forecasting.
- Optimisation of a final London path.

These can be considered later once the base simulation is working.

## 6. Functional Requirements

### 6.1 Data Loading

The application must load base data from JSON files.

Required JSON data types:

- `stations.json`: station metadata.
- `routes.json`: route sections between stations.
- `services.json`: scheduled train services and stops.

The application should validate the loaded data enough to detect missing required fields, invalid times, duplicate IDs, and route references that do not exist.

### 6.2 Timetable Model

The timetable model must represent:

- Service ID.
- Operator.
- Direction.
- Origin and destination.
- Calling points.
- Scheduled arrival times.
- Scheduled departure times.
- Dwell times where relevant.
- Service status, such as scheduled, delayed, or cancelled.

### 6.3 Infrastructure Model

The infrastructure model should initially represent:

- Stations.
- Route sections between stations.
- Approximate running time between route sections.
- Optional platform or capacity constraints where useful.
- Track-aware section capacity using confirmed single, double, and four-track layouts.

The model should be simple enough to maintain manually, but structured enough to support later conflict detection.

### 6.4 Disruption Inputs

The application must allow the user to apply disruptions to a scenario.

Initial disruption types:

- Add delay to a selected service.
- Cancel a selected service.
- Increase dwell time at a selected station.

Later disruption types:

- Add generic rail traffic.
- Block a route section.
- Block or restrict a station/platform.
- Simulate repeated random delays.

### 6.5 Simulation Engine

The simulation engine must:

- Start from the base timetable.
- Apply selected disruptions.
- Recalculate affected arrival and departure times.
- Preserve original scheduled times for comparison.
- Produce a structured result that Streamlit can display.

The engine should be kept separate from the Streamlit UI.

### 6.6 Conflict Detection

The first version should detect simple timetable and operating conflicts.

Initial conflicts:

- Service cancelled.
- Service delayed beyond a selected threshold.
- Missed or weakened connection at Doncaster.
- Train occupying the same route section at the same time, where route-section data allows this.

Later conflicts:

- Platform conflicts.
- Turnaround conflicts.
- Junction conflicts.
- Capacity conflicts caused by a proposed direct London service.

### 6.7 Metrics

The application must calculate and display summary metrics.

Initial metrics:

- Number of services simulated.
- Number of cancelled services.
- Average delay.
- Maximum delay.
- Services delayed beyond threshold.
- On-time percentage.
- Number of detected conflicts.

Later metrics:

- Reliability by direction.
- Reliability by operator.
- Connection success rate at Doncaster.
- Recovery time after disruption.
- Candidate windows for a direct London service.

### 6.8 Streamlit GUI

The Streamlit interface must allow the user to:

- Load the base timetable.
- View services in a table.
- Select a scenario.
- Apply delays or cancellations.
- Run the simulation.
- View changed service times.
- View summary metrics.
- View detected conflicts.

The GUI should make the simulation understandable without requiring the user to read JSON files.

### 6.9 Scenario Comparison

The application should support comparing:

- Base timetable vs disrupted timetable.
- Normal service vs cancellation scenario.
- Current service vs proposed future service.

This can be simple in the MVP and expanded later.

## 7. Non-Functional Requirements

### 7.1 Maintainability

- Simulation logic must live in `simulation/`, not directly inside `app.py`.
- JSON data must live in `data/`.
- Streamlit should mainly handle user input and display.
- Code should be modular enough to add new disruption types and metrics.

### 7.2 Usability

- The GUI should be clear to non-technical users.
- Tables and charts should use plain labels.
- Results should highlight the most important operational effects.
- The user should be able to run a basic scenario without editing code.

### 7.3 Transparency

- The application should show what assumptions are being used.
- Scheduled and simulated times should be distinguishable.
- Disruption inputs should be visible in the results.

### 7.4 Extensibility

The design should support later additions:

- Direct Grimsby-London test services.
- Freight or generic traffic.
- Better route capacity rules.
- Real timetable imports.
- More detailed station and platform modelling.
- Map or timeline visualisations.

## 8. Suggested Data Files

### 8.1 `stations.json`

Should contain:

- Station ID.
- Station name.
- Optional three-letter code.
- Optional latitude and longitude.
- Optional number of platforms.

### 8.2 `routes.json`

Should contain:

- Route ID.
- Direction.
- Ordered station IDs.
- Route sections.
- Approximate running times.
- Optional capacity constraints.

### 8.3 `services.json`

Should contain:

- Service ID.
- Operator.
- Route ID.
- Direction.
- Origin.
- Destination.
- Stops with arrival and departure times.

## 9. Development Phases

### Phase 1: Requirements And Data Shape

- Agree requirements.
- Define JSON schemas.
- Add sample Grimsby-Doncaster data.

### Phase 2: Basic Simulation

- Load timetable data.
- Apply manual delays and cancellations.
- Recalculate simulated times.
- Produce metrics.

### Phase 3: Streamlit MVP

- Build a basic GUI.
- Show timetable and simulation results.
- Add summary metrics.
- Add simple conflict display.

### Phase 4: Corridor Realism

- Add Northern Scunthorpe-Lincoln interaction.
- Add route-section occupancy checks.
- Add more realistic delay propagation.

### Phase 5: Direct London Service Testing

- Insert proposed direct Grimsby-London paths.
- Compare base and proposed scenarios.
- Identify constraints and likely improvements needed.

## 10. Open Questions

- Should the first model start at Grimsby Town or Cleethorpes?
- Which Doncaster connections should count as important London connections?
- Should the simulation represent exact services from a sample day, or a generic weekday pattern?
- What delay threshold should count as significant?
- Should the first Streamlit version favour tables, charts, or a timeline view?
- How detailed should Northern's Scunthorpe-Lincoln service be in the first version?
