export default defineEventHandler(async (event) => {
  const config = useRuntimeConfig()
  const day = getRouterParam(event, 'day')
  const query = getQuery(event)
  const includeProposal = query.include_proposal ?? 'true'

  return await $fetch(`${config.public.apiBase}/simulation/day/${day}`, {
    query: {
      include_proposal: includeProposal,
    },
  })
})
