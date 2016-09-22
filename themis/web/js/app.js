(function () {
  'use strict';

  var app = angular.module('app', [
    'ui.router',
    'ngResource',
    'ngSanitize',
    'tableSort',
    'angular-aui'
  ]);

  app.config(function($stateProvider, $urlRouterProvider) {

    $stateProvider.
    state('clusters', {
      url: '/clusters',
      abstract: true,
      templateUrl: 'views/clusters.html',
      controller: 'clustersCtrl'
    }).
    state('clusters.list', {
      url: '/list',
      views: {
        "list@clusters": {
          templateUrl: 'views/clusters.list.html',
          controller: 'clustersListCtrl'
        }
      }
    }).
    state('clusters.details', {
      url: '/:clusterId/:tab',
      views: {
        "details@clusters": {
          templateUrl: 'views/clusters.details.html',
          controller: 'clustersDetailsCtrl'
        }
      }
    }).
    state('config', {
      url: '/config',
      templateUrl: 'views/config.html',
      controller: 'configCtrl'
    });

    $urlRouterProvider.otherwise('/clusters/list');
  });

  app.factory('restClient', function($resource) {
    return new SwaggerClient({
      url: "//" + document.location.host + "/swagger.json",
      usePromise: true
    });
  });
}());
