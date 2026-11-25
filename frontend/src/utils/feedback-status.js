export const processingLabels = { pending: '待处理', resolved: '已处理' }
export const normalizeProcessingStatus = value => value === 'resolved' ? 'resolved' : 'pending'
export const statusTone = value => value === 'resolved' ? 'success' : 'warning'
