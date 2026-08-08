import { get, post, put, del } from './request'

export interface DeviceListParams {
  code?: string
  type?: string
  status?: string
  project?: string
  page?: number
  pageSize?: number
}

/** 设备列表 */
export function getDevices(params?: DeviceListParams) {
  return get('/api/v1/devices', params)
}

/** 设备详情 */
export function getDevice(code: string) {
  return get(`/api/v1/devices/${code}`)
}

/** 注册设备 */
export function registerDevice(data: any) {
  return post('/api/v1/devices', data)
}

/** 更新设备 */
export function updateDevice(code: string, data: any) {
  return put(`/api/v1/devices/${code}`, data)
}

/** 删除设备 */
export function deleteDevice(code: string) {
  return del(`/api/v1/devices/${code}`)
}

/** 获取设备影子 */
export function getDeviceShadow(code: string) {
  return get(`/api/v1/devices/${code}/shadow`)
}

/** 更新设备期望状态 */
export function updateDesiredState(code: string, desired: any) {
  return put(`/api/v1/devices/${code}/shadow/desired`, desired)
}

/** 设备心跳上报 */
export function deviceHeartbeat(code: string) {
  return post(`/api/v1/devices/${code}/heartbeat`)
}

/** 设备统计信息 */
export function getDeviceStats() {
  return get('/api/v1/devices/stats')
}
