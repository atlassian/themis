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
    state('emr', {
      url: '/emr',
      abstract: true,
      templateUrl: 'views/emr.html',
      controller: 'emrCtrl'
    }).
    state('emr.list', {
      url: '/list',
      views: {
        "list@emr": {
          templateUrl: 'views/emr.list.html',
          controller: 'emrListCtrl'
        }
      }
    }).
    state('emr.details', {
      url: '/:clusterId/:tab',
      views: {
        "details@emr": {
          templateUrl: 'views/emr.details.html',
          controller: 'emrDetailsCtrl'
        }
      }
    }).
    state('kinesis', {
      url: '/kinesis',
      abstract: true,
      templateUrl: 'views/kinesis.html',
      controller: 'kinesisCtrl'
    }).
    state('kinesis.list', {
      url: '/list',
      views: {
        "list@kinesis": {
          templateUrl: 'views/kinesis.list.html',
          controller: 'kinesisListCtrl'
        }
      }
    }).
    state('config', {
      url: '/config',
      templateUrl: 'views/config.html',
      controller: 'configCtrl'
    });

    $urlRouterProvider.otherwise('/emr/list');
  });

  app.factory('restClient', function($resource) {
    return new SwaggerClient({
      url: "//" + document.location.host + "/swagger.json",
      usePromise: true
    });
  });
}());
