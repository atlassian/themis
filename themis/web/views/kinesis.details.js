(function () {
  'use strict';

  var app = angular.module('app');

  app.controller('kinesisDetailsCtrl', function($scope, $stateParams, $interval, restClient, appConfig, appUtils) {

    var client = restClient;
    appConfig.section = 'kinesis';

    $scope.state = {};
    $scope.history = {};
    $scope.refreshing = {};
    $scope.settings = {};
    $scope.active_tab = 1;
    $scope.streamId = $stateParams.streamId;
    $scope.appUtils = appUtils;
    var timer = null;

    if($stateParams.tab) {
      var tabs = {
        'current': 1,
        'history': 2,
        'costs': 3,
        'settings': 4
      }
      $scope.active_tab = tabs[$stateParams.tab];
    }

    $scope.refresh = function() {
      $scope.state.loading = true;
      $scope.history.loading = true;
      client.then(function(client) {

        /* load current state */
        client.default.getKinesisState({stream_id: $scope.streamId}).then(function(obj) {
          $scope.$apply(function() {
            $scope.state.loading = false;
            $scope.state.data = obj.obj;
          });
        }, function(err) {
          $scope.state.loading = false;
          console.log(err);
        });

        /* load history */
        client.default.getKinesisHistory({stream_id: $scope.streamId}).then(function(obj) {
          $scope.$apply(function() {
            $scope.history.loading = false;
            $scope.history.data = obj.obj.results;
          });
        }, function(err) {
          $scope.history.loading = false;
          console.log(err);
        });

        /* load config */
        $scope.loadConfig();
      })
    };

    $scope.loadConfig = function() {
      $scope.settings.loading = true;
      appConfig.getConfig({
          resource: $stateParams.streamId
      }).then(function(config) {
        $scope.settings.loading = false;
        $scope.settings.config = config;
      }, function(err) {
        $scope.settings.loading = false;
        console.log(err);
      });
    };

    $scope.saveConfig = function() {
      $scope.settings.loading = true;
      var params = {
        resource: $stateParams.streamId
      };
      appConfig.setConfig($scope.settings.config, params).
      then(function(config) {
        $scope.settings.loading = false;
        $scope.settings.config = config;
      }, function(err) {
        $scope.settings.loading = false;
        console.log(err);
      });
    };

    $scope.refresh();

  });

})();