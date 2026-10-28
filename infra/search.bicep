// Azure AI Search service backing the Foundry IQ knowledge base (ADR-0005).
param location string = resourceGroup().location
param name string = 'fcc-search-${uniqueString(resourceGroup().id)}'
@description('Principal that creates the index/knowledge base and loads documents.')
param loaderPrincipalId string
@description('Principals (agent identities) that may query the knowledge base.')
param readerPrincipalIds array = []

resource search 'Microsoft.Search/searchServices@2025-05-01' = {
  name: name
  location: location
  sku: { name: 'basic' }
  properties: {
    replicaCount: 1
    partitionCount: 1
    semanticSearch: 'free'
    disableLocalAuth: true
  }
}

var serviceContributor = '7ca78c08-252a-4471-8644-bb5ff32d4ba0'
var indexDataContributor = '8ebe5a00-799e-43f5-93ac-243d3dce84a7'
var indexDataReader = '1407120a-92aa-4202-b7e9-c0e197c71c8f'

resource loaderSvc 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: search
  name: guid(search.id, loaderPrincipalId, serviceContributor)
  properties: {
    principalId: loaderPrincipalId
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', serviceContributor)
  }
}

resource loaderData 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: search
  name: guid(search.id, loaderPrincipalId, indexDataContributor)
  properties: {
    principalId: loaderPrincipalId
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', indexDataContributor)
  }
}

resource readers 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for p in readerPrincipalIds: {
  scope: search
  name: guid(search.id, p, indexDataReader)
  properties: {
    principalId: p
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', indexDataReader)
  }
}]

output searchName string = search.name
output searchEndpoint string = 'https://${search.name}.search.windows.net'
