export function statusClass(status: string) {
  return `status-pill status-${status.toLowerCase().replace(/_/g, '-')}`
}

export function formatStatus(status: string) {
  return status.replace(/_/g, ' ')
}

export function timeAgo(iso: string): string {
  const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.round(hours / 24)
  return `${days}d ago`
}
