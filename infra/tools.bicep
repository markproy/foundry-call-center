// Tool backends: Cosmos DB (serverless, Entra-only) + Azure Functions (Flex Consumption).
// Deployed into the same resource group as the Foundry project (see ADR-0003).
targetScope = 'resourceGroup'

param location string = resourceGroup().location
param prefix string = 'fcc'
@description('Object id of the human/CI principal that loads seed data.')
param loaderPrincipalId string
@description('Client id of the Entra app registration that represents the tools API (audience api://<id>).')
param toolsApiClientId string

var token = take(uniqueString(resourceGroup().id), 6)
var cosmosName = '${prefix}-cosmos-${token}'
var storageName = take(replace('${prefix}st${token}', '-', ''), 24)
var planName = '${prefix}-plan-${token}'
var funcName = '${prefix}-tools-${token}'
var dbName = 'callcenter'

var containers = [
  { name: 'members', pk: '/member_id' }
  { name: 'providers', pk: '/provider_id' }
  { name: 'claims', pk: '/member_id' }
  { name: 'appointments', pk: '/member_id' }
  { name: 'prescriptions', pk: '/member_id' }
  { name: 'evalruns', pk: '/id' }
]

resource cosmos 'Microsoft.DocumentDB/databaseAccounts@2024-11-15' = {
  name: cosmosName
  location: location
  kind: 'GlobalDocumentDB'
  properties: {
    databaseAccountOfferType: 'Standard'
    locations: [{ locationName: location, failoverPriority: 0 }]
    capabilities: [{ name: 'EnableServerless' }]
    disableLocalAuth: true
  }
}

resource db 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2024-11-15' = {
  parent: cosmos
  name: dbName
  properties: { resource: { id: dbName } }
}

resource cont 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-11-15' = [for c in containers: {
  parent: db
  name: c.name
  properties: {
    resource: {
      id: c.name
      partitionKey: { paths: [c.pk], kind: 'Hash' }
    }
  }
}]

// Built-in "Cosmos DB Built-in Data Contributor"
var cosmosDataContributor = '${cosmos.id}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002'

resource loaderRole 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-11-15' = {
  parent: cosmos
  name: guid(cosmos.id, loaderPrincipalId, 'data')
  properties: {
    roleDefinitionId: cosmosDataContributor
    principalId: loaderPrincipalId
    scope: cosmos.id
  }
}

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageName
  location: location
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: {
    allowSharedKeyAccess: false
    allowBlobPublicAccess: false
    minimumTlsVersion: 'TLS1_2'
  }
}

resource blobSvc 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
}

resource deployContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobSvc
  name: 'deploymentpackage'
}

resource plan 'Microsoft.Web/serverfarms@2024-04-01' = {
  name: planName
  location: location
  kind: 'functionapp'
  sku: { name: 'FC1', tier: 'FlexConsumption' }
  properties: { reserved: true }
}

resource func 'Microsoft.Web/sites@2024-04-01' = {
  name: funcName
  location: location
  kind: 'functionapp,linux'
  identity: { type: 'SystemAssigned' }
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    functionAppConfig: {
      deployment: {
        storage: {
          type: 'blobContainer'
          value: '${storage.properties.primaryEndpoints.blob}deploymentpackage'
          authentication: { type: 'SystemAssignedIdentity' }
        }
      }
      scaleAndConcurrency: { maximumInstanceCount: 40, instanceMemoryMB: 2048 }
      runtime: { name: 'python', version: '3.11' }
    }
    siteConfig: {
      appSettings: [
        { name: 'AzureWebJobsStorage__accountName', value: storage.name }
        { name: 'COSMOS_ENDPOINT', value: cosmos.properties.documentEndpoint }
        { name: 'COSMOS_DATABASE', value: dbName }
      ]
    }
  }
  dependsOn: [deployContainer]
}

resource auth 'Microsoft.Web/sites/config@2024-04-01' = {
  parent: func
  name: 'authsettingsV2'
  properties: {
    platform: { enabled: true }
    globalValidation: {
      requireAuthentication: true
      unauthenticatedClientAction: 'Return401'
    }
    identityProviders: {
      azureActiveDirectory: {
        enabled: true
        registration: {
          clientId: toolsApiClientId
          // v1 issuer: managed identity tokens are v1 tokens
          openIdIssuer: 'https://sts.windows.net/${tenant().tenantId}/'
        }
        validation: { allowedAudiences: ['api://${toolsApiClientId}', toolsApiClientId] }
      }
    }
    login: { tokenStore: { enabled: false } }
  }
}

var storageBlobDataOwner = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'b7e6dc6d-f1e8-4753-8033-0f276bb0955b')

resource funcStorageRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: storage
  name: guid(storage.id, func.id, 'blobowner')
  properties: {
    roleDefinitionId: storageBlobDataOwner
    principalId: func.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource funcCosmosRole 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-11-15' = {
  parent: cosmos
  name: guid(cosmos.id, func.id, 'data')
  properties: {
    roleDefinitionId: cosmosDataContributor
    principalId: func.identity.principalId
    scope: cosmos.id
  }
}

output cosmosEndpoint string = cosmos.properties.documentEndpoint
output cosmosDatabase string = dbName
output toolsApiAudience string = 'api://${toolsApiClientId}'
output functionAppName string = func.name
output functionAppHost string = func.properties.defaultHostName
