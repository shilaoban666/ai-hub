import { reactive } from 'vue'
import { createServiceRecovery } from './service-recovery.js'

export const serviceAvailability = reactive({})
const recoveries = new Map()

export function serviceRecoveryFor(baseURL) {
  if (!recoveries.has(baseURL)) {
    recoveries.set(baseURL, createServiceRecovery({
      onChange: state => { serviceAvailability[baseURL] = state },
    }))
  }
  return recoveries.get(baseURL)
}

export function retryUnavailableServices() {
  recoveries.forEach(recovery => recovery.retryNow())
}
