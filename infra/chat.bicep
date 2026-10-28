// Chat backend + UI on Azure Container Apps (no VM quota needed), see ADR-0007.
// Two-step deploy (scripts/deploy_chat.sh): this template creates the registry,
// environment and an app on a placeholder image; the script then builds the real
// image with `az acr build` and re-runs this template with useAcr=true.
targetScope = 'resourceGroup'

param location string = resourceGroup().location
param prefix string = 'fcc'
param foundryProjectEndpoint string
@description('Image to run. Starts as a placeholder; the deploy script updates it.')
param image string = 'mcr.microsoft.com/k8se/quickstart:latest'
param useAcr bool = false
@secure()
@description('Optional shared secret the browser must send in x-demo-secret. Empty disables the gate.')
param demoSharedSecret string = ''

@description('Cosmos endpoint holding the evalruns container (eval history in the admin dashboard).')
param cosmosEndpoint string = ''
@secure()
@description('Secret for the /admin API (x-admin-secret). Empty disables the admin API.')
param adminSecret string = ''
@description('Attach prompts and answers to traces. Leave off for real member data.')
param captureContent bool = false

var token = take(uniqueString(resourceGroup().id), 6)
var acrName = '${prefix}acr${token}'
var appName = '${prefix}-chat-${token}'
var baseEnv = [
  { name: 'FOUNDRY_PROJECT_ENDPOINT', value: foundryProjectEndpoint }
  { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsights.properties.ConnectionString }
  { name: 'APPINSIGHTS_APP_ID', value: appInsights.properties.AppId }
  { name: 'COSMOS_ENDPOINT', value: cosmosEndpoint }
  { name: 'CAPTURE_CONTENT', value: string(captureContent) }
]
var adminEnv = empty(adminSecret) ? [] : [{ name: 'ADMIN_SECRET', secretRef: 'admin-secret' }]
var secretEnv = empty(demoSharedSecret) ? [] : [{ name: 'DEMO_SHARED_SECRET', secretRef: 'demo-secret' }]

resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: '${prefix}-logs-${token}'
  location: location
  properties: { sku: { name: 'PerGB2018' }, retentionInDays: 30 }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: '${prefix}-appi-${token}'
  location: location
  kind: 'web'
  properties: { Application_Type: 'web', WorkspaceResourceId: logs.id }
}

// Dashboard (ADR-0009). Tiles are KQL over the chat_turn / classify / specialist spans.
resource dashboard 'Microsoft.Insights/workbooks@2023-06-01' = {
  name: guid(resourceGroup().id, 'fcc-dashboard')
  location: location
  kind: 'shared'
  properties: {
    displayName: 'Foundry Call Center - operations'
    category: 'workbook'
    sourceId: appInsights.id
    serializedData: loadTextContent('workbook.json')
  }
}

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: acrName
  location: location
  sku: { name: 'Basic' }
  properties: { adminUserEnabled: false }
}

resource env 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: '${prefix}-env-${token}'
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logs.properties.customerId
        sharedKey: logs.listKeys().primarySharedKey
      }
    }
  }
}

resource app 'Microsoft.App/containerApps@2024-03-01' = {
  name: appName
  location: location
  identity: { type: 'SystemAssigned' }
  properties: {
    managedEnvironmentId: env.id
    configuration: {
      ingress: { external: true, targetPort: useAcr ? 8000 : 80, transport: 'auto' }
      registries: useAcr ? [{ server: acr.properties.loginServer, identity: 'system' }] : []
      secrets: concat(
        empty(demoSharedSecret) ? [] : [{ name: 'demo-secret', value: demoSharedSecret }],
        empty(adminSecret) ? [] : [{ name: 'admin-secret', value: adminSecret }]
      )
    }
    template: {
      containers: [
        {
          name: 'chat'
          image: image
          resources: { cpu: json('0.5'), memory: '1Gi' }
          env: concat(baseEnv, secretEnv, adminEnv)
        }
      ]
      scale: { minReplicas: 1, maxReplicas: 3 }
    }
  }
}

output appName string = app.name
output acrName string = acr.name
output acrLoginServer string = acr.properties.loginServer
output principalId string = app.identity.principalId
output url string = 'https://${app.properties.configuration.ingress.fqdn}'
output appInsightsName string = appInsights.name
output appInsightsId string = appInsights.id
