(function () {
  'use strict';

  var app = angular.module('app');

  app.controller('emrCtrl', function($scope) {

    $scope.dialog = {
      visible: false
    };

    $scope.dialog = function(title, text, callback, cancelCallback) {
      $scope.dialog.title = title;
      $scope.dialog.text = text;
      $scope.dialog.callback = callback;
      $scope.dialog.visible = true;
      $scope.dialog.ok = function() {
        $scope.dialog.visible = false;
        if(callback) callback();
      };
      $scope.dialog.cancel = function() {
        $scope.dialog.visible = false;
        if(cancelCallback) cancelCallback();
      };
    };

  });

})();