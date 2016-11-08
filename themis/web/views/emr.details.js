(function () {
  'use strict';

  var app = angular.module('app');

  app.controller('emrDetailsCtrl', function($scope, $stateParams, $interval, restClient, appConfig, appUtils) {

    var client = restClient;
    appConfig.section = 'emr';

    $scope.state = {};
    $scope.history = {};
    $scope.refreshing = {};
    $scope.savings = {};
    $scope.settings = {};
    $scope.active_tab = 1;
    $scope.clusterId = $stateParams.clusterId;
    $scope.baseline_nodes = 20;
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

    var startLoop = function(saved_per_second) {
      stopLoop();
      timer = $interval(function() {
        $scope.savings.saved += saved_per_second;
      }, 1000);
    };

    var stopLoop = function() {
      if(timer) {
        $interval.cancel(timer);
        timer = undefined;
      }
    };

    var loadStateData = function(data) {
      $scope.$apply(function() {
        $scope.state.data = data;
      });
    };

    var loadHistoryData = function(data) {
      $scope.$apply(function() {
        $scope.history.data = data.results;
      });
    };

    var loadCostsData = function(data) {
      $scope.$apply(function() {
        $scope.savings = data.results;
        $scope.baseline_nodes = data.baseline_nodes;
        if(!$scope.savings.saved) {
          $scope.savings.saved = 'n/a';
        } else {
          startLoop($scope.savings.saved_per_second);
        }
      });
    };

    $scope.refresh = function() {
      $scope.state.loading = true;
      $scope.history.loading = true;
      $scope.savings.loading = true;
      client.then(function(client) {

        /* load current state */
        client.default.getEmrState({cluster_id: $scope.clusterId}).then(function(obj) {
          $scope.state.loading = false;
          loadStateData(obj.obj);
        }, function(err) {
          $scope.state.loading = false;
          console.log(err);
        });

        /* load history */
        client.default.getEmrHistory({cluster_id: $scope.clusterId}).then(function(obj) {
          $scope.history.loading = false;
          loadHistoryData(obj.obj);
        }, function(err) {
          $scope.history.loading = false;
          console.log(err);
        });

        /* load savings */
        $scope.savings.saved = 'n/a';
        client.default.getEmrCosts({request: {
            cluster_id: $scope.clusterId
          }
        }).then(function(obj) {
          $scope.savings.loading = false;
          loadCostsData(obj.obj);
        }, function(err) {
          $scope.savings.loading = false;
          console.log(err);
        });

        /* load config */
        $scope.loadConfig();
        $scope.$apply();
      })
    };

    $scope.restartNode = function(node) {
      client.then(function(client) {
        /* load current state */
        $scope.dialog("Confirm Restart", "This will send the SHUTTING_DOWN signal to this node, causing the node to restart. Continue?", function(result) {
          $scope.refreshing[node.host] = true;
          client.default.restartEmrNode({request: {
                cluster_id: $scope.clusterId,
                node_host: node.host}
          }).then(function(obj) {
            $scope.refreshing[node.host] = false;
            $scope.$apply();
          }, function(err) {
            console.log(err);
            $scope.refreshing[node.host] = false;
            $scope.$apply();
          });
        });
        $scope.$apply();
      });
    };

    $scope.loadConfig = function() {
      $scope.settings.loading = true;
      appConfig.getConfig({
          resource: $stateParams.clusterId
      }).then(function(config) {
        $scope.settings.loading = false;
        $scope.settings.config = config;
      }, function(err) {
        $scope.settings.loading = false;
        console.log(err);
      });
    };

    $scope.saveConfig = function() {
      $scope.settings.saving = true;
      var params = {
        resource: $stateParams.clusterId
      };
      appConfig.setConfig($scope.settings.config, params).
      then(function(config) {
        $scope.settings.saving = false;
        $scope.settings.config = config;
      }, function(err) {
        $scope.settings.saving = false;
        console.log(err);
      });
    };

    $scope.$on('$destroy', function() {
      stopLoop();
    });

    $scope.refresh();

  });

})();