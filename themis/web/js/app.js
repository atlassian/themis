(function () {
  'use strict';

  var app = angular.module('app', [
    'ui.router',
    'ngResource',
    'ngSanitize',
    'tableSort',
    'angular-aui',
    'angular-growl'
  ]);

  app.factory('appConfig', function(restClient, growl) {
    var client = restClient;
    return {
      section: 'general',
      extractConfigValue: function(key, configs) {
        var result = null;
        configs.forEach(function(config) {
          if(config.key == key) {
            result = config.value;
          }
        });
        return result;
      },
      injectConfigValue: function(key, value, configs) {
        configs.forEach(function(config) {
          if(config.key == key) {
            config.value = value;
          }
        });
        return configs;
      },
      getConfigValue: function(key, configs) {
        if(configs)
          return this.extractConfigValue(key, configs);
        var self = this;
        return this.getConfig(function(configs) {
          var result = self.extractConfigValue(key, configs);
          return result;
        });
      },
      setConfigValue: function(key, value, configs) {
        if(configs) {
          this.injectConfigValue(key, value, configs);
          return setConfig(configs);
        }
        var self = this;
        return this.getConfig(function(configs) {
          self.injectConfigValue(key, value, configs);
          return self.setConfig(configs);
        });
      },
      getConfig: function(params, callback) {
        if(typeof params == 'function') {
          callback = params;
          params = null;
        }
        if(!params) {
          params = {};
        }
        var section = params['section'] || this.section;
        var resource = params['resource'];
        return client.then(function(client) {
          var clientMethod = resource ? client.default.getConfig : client.default.getGlobalConfig;
          return clientMethod({
            section: section,
            resource: resource
          }).then(function(config) {
            config = config.obj.config;
            if(callback)
              return callback(config);
            return config;
          });
        });
      },
      setConfig: function(config, params, callback) {
        if(typeof params == 'function') {
          callback = params;
          params = null;
        }
        if(!params) {
          params = {};
        }
        var section = params['section'] || this.section;
        var resource = params['resource'];
        return client.then(function(client) {
          var clientMethod = resource ? client.default.setConfig : client.default.setGlobalConfig;
          return clientMethod({
            config: config,
            section: section,
            resource: resource
          }).then(function(config) {
            growl.success('Configuration successfully updated.', {ttl: 2500, disableCountDown: true});
            config = config.obj.config;
            if(callback)
              return callback(config);
            return config;
          });
        });
      }
    };
  });

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
