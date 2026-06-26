<script setup lang="ts">
type Day =
  | 'monday'
  | 'tuesday'
  | 'wednesday'
  | 'thursday'
  | 'friday'
  | 'saturday'
  | 'sunday'

type RollingStockSummary = {
  id: string | null
  name: string | null
  family: string | null
  cars: number | null
  length_metres: number | null
  seats: number | null
  maximum_speed_mph: number | null
  traction: string | null
  coupling: string | null
}

type ServiceSummary = {
  service_id: string
  service_label: string
  operator: string
  timetable_type: string
  route_id: string
  route: string
  direction: string
  origin: string
  destination: string
  first_departure: string | null
  final_arrival: string | null
  status: string
  delay_minutes: number
  service_days: string[]
  footnote_codes: string[]
  rolling_stock: RollingStockSummary | null
}

type StopTimeRow = {
  service_id: string
  service_label: string
  operator: string
  timetable_type: string
  route: string
  station: string
  stop_index: number
  arrival: string | null
  departure: string | null
  status: string
  delay_minutes: number
  rolling_stock: RollingStockSummary | null
}

type ConflictRow = {
  section: string
  first_service: string
  first_operator: string
  first_train: string | null
  first_cars: number | null
  second_service: string
  second_operator: string
  second_train: string | null
  second_cars: number | null
  overlap_start: string
  overlap_end: string
  overlap_minutes: number
}

type OccupationRow = {
  service_id: string
  service_label: string
  operator: string
  route: string
  section: string
  track_layout: string
  enter: string
  exit: string
  duration_minutes: number
  status: string
  delay_minutes: number
  rolling_stock: RollingStockSummary | null
}

type DailyMetrics = {
  services: number
  proposed_services: number
  active_services: number
  delayed_services: number
  cancelled_services: number
  operators: number
  routes: number
  known_seats: number
  unknown_capacity_services: number
  section_occupations: number
  conflicts: number
  conflict_minutes: number
}

type DaySimulationResponse = {
  day: Day
  include_proposal: boolean
  metrics: DailyMetrics
  services: ServiceSummary[]
  timetable: StopTimeRow[]
  conflicts: ConflictRow[]
  occupations: OccupationRow[]
  warnings: string[]
}

const days: Day[] = [
  'monday',
  'tuesday',
  'wednesday',
  'thursday',
  'friday',
  'saturday',
  'sunday',
]

const selectedDay = ref<Day>('monday')
const includeProposal = ref(true)
const selectedOperator = ref('all')
const selectedRoute = ref('all')
const activeTable = ref<'services' | 'conflicts' | 'occupations' | 'timetable'>('services')

const dayLabel = (day: string) => day.charAt(0).toUpperCase() + day.slice(1)
const formatNumber = (value: number) => new Intl.NumberFormat('en-GB').format(value)
const formatTrackLayout = (value: string) => value.replaceAll('_', ' ')
const trainLabel = (stock: RollingStockSummary | null) => {
  if (!stock?.name) return 'Unknown'
  return stock.cars ? `${stock.name} (${stock.cars}-car)` : stock.name
}

const apiPath = computed(
  () => `/api/simulation/day/${selectedDay.value}?include_proposal=${includeProposal.value}`,
)

const {
  data,
  pending,
  error,
  refresh,
} = await useFetch<DaySimulationResponse>(apiPath, {
  server: false,
  watch: [selectedDay, includeProposal],
})

watch([selectedDay, includeProposal], () => {
  selectedOperator.value = 'all'
  selectedRoute.value = 'all'
})

const operators = computed(() => {
  const values = data.value?.services.map((service) => service.operator) ?? []
  return [...new Set(values)].sort()
})

const routes = computed(() => {
  const values = data.value?.services.map((service) => service.route) ?? []
  return [...new Set(values)].sort()
})

const serviceMatchesFilters = (service: { operator: string, route: string }) => {
  return (
    (selectedOperator.value === 'all' || service.operator === selectedOperator.value)
    && (selectedRoute.value === 'all' || service.route === selectedRoute.value)
  )
}

const filteredServices = computed(() => {
  return data.value?.services.filter(serviceMatchesFilters) ?? []
})

const filteredConflicts = computed(() => {
  const serviceKeys = new Set(
    filteredServices.value.map((service) => `${service.operator}:${service.service_label}`),
  )
  return data.value?.conflicts.filter((conflict) => {
    if (selectedOperator.value !== 'all') {
      return conflict.first_operator === selectedOperator.value || conflict.second_operator === selectedOperator.value
    }
    if (selectedRoute.value !== 'all') {
      return serviceKeys.has(`${conflict.first_operator}:${conflict.first_service}`)
        || serviceKeys.has(`${conflict.second_operator}:${conflict.second_service}`)
    }
    return true
  }) ?? []
})

const filteredOccupations = computed(() => {
  return data.value?.occupations.filter(serviceMatchesFilters).slice(0, 250) ?? []
})

const filteredTimetable = computed(() => {
  return data.value?.timetable.filter(serviceMatchesFilters).slice(0, 300) ?? []
})

const currentMetrics = computed(() => data.value?.metrics)

const metricCards = computed(() => {
  const metrics = currentMetrics.value
  if (!metrics) return []

  return [
    { label: 'Services', value: formatNumber(metrics.services), tone: 'ink' },
    { label: 'Active', value: formatNumber(metrics.active_services), tone: 'green' },
    { label: 'Conflicts', value: formatNumber(metrics.conflicts), tone: metrics.conflicts > 0 ? 'red' : 'green' },
    { label: 'Conflict min', value: formatNumber(metrics.conflict_minutes), tone: metrics.conflict_minutes > 0 ? 'amber' : 'green' },
    { label: 'Known seats', value: formatNumber(metrics.known_seats), tone: 'blue' },
    { label: 'Occupations', value: formatNumber(metrics.section_occupations), tone: 'ink' },
  ]
})
</script>

<template>
  <div class="min-h-screen bg-[#f4f2ed] text-[#171717]">
    <NuxtRouteAnnouncer />

    <header class="border-b border-[#d7d2c8] bg-[#fbfaf7]">
      <div class="mx-auto flex max-w-[1600px] flex-col gap-5 px-5 py-5 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p class="text-xs font-semibold uppercase text-[#6f6a60]">Operational simulation</p>
          <h1 class="mt-1 text-2xl font-semibold text-[#171717]">Grimsby-London Rail Planning</h1>
          <p class="mt-2 max-w-3xl text-sm text-[#5f5a51]">
            Day-by-day service, conflict, section occupation, and rolling-stock view.
          </p>
        </div>

        <div class="flex flex-wrap items-center gap-3">
          <label class="control-toggle">
            <input v-model="includeProposal" type="checkbox" class="h-4 w-4 accent-[#235c4f]">
            <span>Grand Central proposal</span>
          </label>

          <button class="command-button" :disabled="pending" @click="refresh()">
            Refresh
          </button>
        </div>
      </div>
    </header>

    <main class="mx-auto max-w-[1600px] px-5 py-5">
      <section class="toolbar-band">
        <div class="day-grid" aria-label="Operating day">
          <button
            v-for="day in days"
            :key="day"
            type="button"
            class="day-button"
            :class="{ 'day-button-active': selectedDay === day }"
            @click="selectedDay = day"
          >
            {{ dayLabel(day) }}
          </button>
        </div>

        <div class="filter-grid">
          <label class="filter-field">
            <span>Operator</span>
            <select v-model="selectedOperator">
              <option value="all">All operators</option>
              <option v-for="operator in operators" :key="operator" :value="operator">
                {{ operator }}
              </option>
            </select>
          </label>

          <label class="filter-field">
            <span>Route</span>
            <select v-model="selectedRoute">
              <option value="all">All routes</option>
              <option v-for="route in routes" :key="route" :value="route">
                {{ route }}
              </option>
            </select>
          </label>
        </div>
      </section>

      <div v-if="error" class="state-panel border-[#c8553d] bg-[#fff5f1] text-[#7a2f20]">
        Backend data could not be loaded. Start FastAPI on port 8000 and refresh this view.
      </div>

      <div v-else-if="pending && !data" class="state-panel border-[#d7d2c8] bg-[#fbfaf7] text-[#5f5a51]">
        Loading simulation data.
      </div>

      <template v-else-if="data">
        <section class="metric-grid">
          <article
            v-for="metric in metricCards"
            :key="metric.label"
            class="metric-card"
            :class="`metric-${metric.tone}`"
          >
            <span>{{ metric.label }}</span>
            <strong>{{ metric.value }}</strong>
          </article>
        </section>

        <section v-if="data.warnings.length" class="state-panel border-[#d39b31] bg-[#fff8e6] text-[#714d08]">
          {{ data.warnings.length }} backend warning{{ data.warnings.length === 1 ? '' : 's' }} returned.
        </section>

        <section class="content-shell">
          <nav class="table-tabs" aria-label="Dashboard table">
            <button
              type="button"
              :class="{ 'table-tab-active': activeTable === 'services' }"
              @click="activeTable = 'services'"
            >
              Services
            </button>
            <button
              type="button"
              :class="{ 'table-tab-active': activeTable === 'conflicts' }"
              @click="activeTable = 'conflicts'"
            >
              Conflicts
            </button>
            <button
              type="button"
              :class="{ 'table-tab-active': activeTable === 'occupations' }"
              @click="activeTable = 'occupations'"
            >
              Occupations
            </button>
            <button
              type="button"
              :class="{ 'table-tab-active': activeTable === 'timetable' }"
              @click="activeTable = 'timetable'"
            >
              Timetable
            </button>
          </nav>

          <div class="table-wrap">
            <table v-if="activeTable === 'services'" class="data-table">
              <thead>
                <tr>
                  <th>Dep</th>
                  <th>Operator</th>
                  <th>Route</th>
                  <th>Origin</th>
                  <th>Destination</th>
                  <th>Train</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="service in filteredServices" :key="service.service_id">
                  <td class="font-semibold">{{ service.first_departure ?? service.service_label }}</td>
                  <td>{{ service.operator }}</td>
                  <td>{{ service.route }}</td>
                  <td>{{ service.origin }}</td>
                  <td>{{ service.destination }}</td>
                  <td>{{ trainLabel(service.rolling_stock) }}</td>
                  <td>
                    <span class="status-pill" :class="`status-${service.status}`">
                      {{ service.status }}
                    </span>
                  </td>
                </tr>
              </tbody>
            </table>

            <table v-else-if="activeTable === 'conflicts'" class="data-table">
              <thead>
                <tr>
                  <th>Section</th>
                  <th>First</th>
                  <th>Second</th>
                  <th>Window</th>
                  <th>Minutes</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="conflict in filteredConflicts" :key="`${conflict.section}-${conflict.first_service}-${conflict.second_service}-${conflict.overlap_start}`">
                  <td class="font-semibold">{{ conflict.section }}</td>
                  <td>{{ conflict.first_operator }} {{ conflict.first_service }} · {{ conflict.first_train ?? 'Unknown' }}</td>
                  <td>{{ conflict.second_operator }} {{ conflict.second_service }} · {{ conflict.second_train ?? 'Unknown' }}</td>
                  <td>{{ conflict.overlap_start }}-{{ conflict.overlap_end }}</td>
                  <td>{{ conflict.overlap_minutes }}</td>
                </tr>
                <tr v-if="filteredConflicts.length === 0">
                  <td colspan="5" class="empty-cell">No conflicts for the current filters.</td>
                </tr>
              </tbody>
            </table>

            <table v-else-if="activeTable === 'occupations'" class="data-table">
              <thead>
                <tr>
                  <th>Enter</th>
                  <th>Service</th>
                  <th>Operator</th>
                  <th>Section</th>
                  <th>Track</th>
                  <th>Duration</th>
                  <th>Train</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="occupation in filteredOccupations" :key="`${occupation.service_id}-${occupation.section}-${occupation.enter}`">
                  <td class="font-semibold">{{ occupation.enter }}</td>
                  <td>{{ occupation.service_label }}</td>
                  <td>{{ occupation.operator }}</td>
                  <td>{{ occupation.section }}</td>
                  <td>{{ formatTrackLayout(occupation.track_layout) }}</td>
                  <td>{{ occupation.duration_minutes }} min</td>
                  <td>{{ trainLabel(occupation.rolling_stock) }}</td>
                </tr>
              </tbody>
            </table>

            <table v-else class="data-table">
              <thead>
                <tr>
                  <th>Service</th>
                  <th>Operator</th>
                  <th>Station</th>
                  <th>Arr</th>
                  <th>Dep</th>
                  <th>Route</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in filteredTimetable" :key="`${row.service_id}-${row.stop_index}`">
                  <td class="font-semibold">{{ row.service_label }}</td>
                  <td>{{ row.operator }}</td>
                  <td>{{ row.station }}</td>
                  <td>{{ row.arrival ?? '-' }}</td>
                  <td>{{ row.departure ?? '-' }}</td>
                  <td>{{ row.route }}</td>
                  <td>
                    <span class="status-pill" :class="`status-${row.status}`">
                      {{ row.status }}
                    </span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>
      </template>
    </main>
  </div>
</template>
