(function () {
  'use strict';

  var app = angular.module('app');

  app.controller('configCtrl', function($scope, restClient, appConfig) {

    var client = restClient;
    appConfig.section = 'general';

    $scope.load = function() {
      $scope.loading = true;
      appConfig.getConfig()
      .then(function(config) {
        $scope.loading = false;
        $scope.$apply(function(){
          $scope.config = config;
        });
      }, function(err) {
        $scope.loading = false;
        console.log(err);
      });
    };

    $scope.save = function() {
      /* load config */
      appConfig.setConfig($scope.config)
      .then(function(config) {
        $scope.$apply(function(){
          $scope.config = config;
        });
      }, function(err) {
        console.log(err);
      });
    };

    $scope.load();

  });

})();